"""Standalone JTCom switch client and canonical configuration API."""

from __future__ import annotations

import datetime
import logging
import pathlib
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from cgiswitch.client.errors import (
    JTComApplyError,
    JTComError,
    JTComPolicyError,
    JTComStateError,
    JTComVerificationError,
)
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.device import DeviceInfo
from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
from cgiswitch.model.port import PortOperStatus, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry
from cgiswitch.parser.device import parse_device_info
from cgiswitch.parser.port import parse_port_page
from cgiswitch.parser.vlan import parse_port_vlan_settings, parse_static_vlans
from cgiswitch.utils.device_diff import build_device_plan
from cgiswitch.utils.normalize import normalize_device_config
from cgiswitch.utils.operations import compile_apply_operations, compile_membership_operations
from cgiswitch.utils.policy import evaluate_device_policy
from cgiswitch.utils.port_vlan_input import merge_port_vlan_membership_inputs
from cgiswitch.utils.render import render_diff, render_effective_diff
from cgiswitch.utils.validation import validate_desired_config
from cgiswitch.utils.vlan_membership import (
    PortMembershipMap,
    VlanMembershipPlan,
    build_current_per_port_from_jtcom_readback,
    build_current_per_port_from_vlans,
    copy_port_state,
    diff_membership_maps,
    plan_vlan_membership_changes,
    port_name_to_id,
    serialize_membership_map,
)
from cgiswitch.vendor.jtcom.endpoints import (
    DEVICE_INFO,
    PORT_SETTINGS,
    VLAN_PORT_BASED,
    VLAN_STATIC,
)

logger = logging.getLogger(__name__)

class JTComSwitch:
    """Standalone client for JTCom CGI-based Ethernet switches.

    Communicates with the switch via its HTTP CGI web interface.
    HTML responses are parsed with BeautifulSoup to extract structured data.

    Use read_device_info(), read_ports() and read_vlans() for readback.
    apply() manages VLANs and ports; bootstrap manages credentials and IP.
    Writes are verified but are not transactional and have no automatic rollback.

    Args:
        hostname: IP address or hostname of the switch, optionally including
            the URL scheme (e.g. ``http://192.0.2.10``).
        username: Login username.
        password: Login password.
        connection: Typed HTTP connection settings.
        policy: Instance policy used by every apply call.
    """

    def __init__(
        self,
        hostname: str,
        username: str,
        password: str,
        *,
        connection: JTComConnectionOptions | None = None,
        policy: ApplyPolicy | None = None,
    ) -> None:
        self.hostname = hostname
        self.username = username
        self.password = password
        self.connection = connection or JTComConnectionOptions()
        self.policy = policy or ApplyPolicy()
        self._verify_tls = self.connection.verify_tls
        self._port = (
            self.connection.port
            if self.connection.port is not None
            else (443 if self._verify_tls else 80)
        )
        self.timeout = self.connection.timeout
        self._session: JTComSession | None = None

        logger.debug(
            "JTComSwitch initialised: host=%s port=%d user=%s",
            self.hostname,
            self._port,
            self.username,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open an HTTP session and authenticate with the switch.

        If a session is already open it is closed first to prevent resource
        leaks.

        Raises:
            JTComAuthError: If login is rejected by the switch.
        """
        if self._session is not None:
            logger.debug("Session already open; closing before re-open")
            self.close()
        base_url = self._build_base_url()
        logger.info("Opening connection to %s", base_url)
        creds = JTComCredentials(username=self.username, password=self.password)
        self._session = JTComSession(
            base_url=base_url,
            credentials=creds,
            timeout_s=float(self.timeout),
            verify_tls=self._verify_tls,
        )
        try:
            self._session.login()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Logout and close the HTTP session (best-effort; never raises)."""
        if self._session is not None:
            logger.info("Closing connection to %s", self.hostname)
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                logger.debug("Session close failed (ignored)", exc_info=True)
            finally:
                self._session = None

    def __enter__(self) -> JTComSwitch:
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read_device_info(self) -> DeviceInfo:
        """Read and parse the switch device information page."""
        session = self._require_session()
        return parse_device_info(session.get(DEVICE_INFO))

    def read_ports(self) -> tuple[list[PortSettings], list[PortOperStatus]]:
        """Read administrative and operational port information."""
        session = self._require_session()
        return parse_port_page(session.get(PORT_SETTINGS))

    def read_vlans(self) -> dict[int, VlanEntry]:
        """Read VLANs with canonicalized port membership."""
        return self._fetch_vlan_state(self._require_session())

    def is_connected(self) -> bool:
        """Return whether an authenticated session is open."""
        return self._session is not None and self._session.logged_in

    def apply(
        self,
        desired: DeviceConfig,
        *,
        check_mode: bool = False,
    ) -> dict[str, Any]:
        """Apply an incremental device configuration to the switch idempotently.

        Reads the current switch state, normalizes both current and desired
        configs, computes a deterministic change plan, and applies only what
        has changed.  A post-apply read-back verifies the result.

        VLAN entries in *desired* carry ``state`` (``"present"`` or
        ``"absent"``); port entries are patch-style and only supplied fields
        are changed. Unlisted entries request no direct change; membership intent
        can also affect membership of other VLANs.

        Args:
            desired: Incremental :class:`~cgiswitch.model.config.DeviceConfig`.
            check_mode: If ``True``, read state and return a plan with no backup
                or configuration writes. Authentication may use POST requests.
                The instance policy configured at construction is used.

        Returns:
            A dict with keys:

            - ``"changed"`` — ``True`` if any changes were (or would be) applied.
            - ``"blocked"`` — whether policy forbids the planned changes.
            - ``"violations"`` — structured policy failures, separate from warnings.
            - ``"diff"`` — rendered plan dict from :func:`~cgiswitch.utils.render.render_diff`.
            - ``"backup_file"`` — path to the backup, or ``""`` if skipped.
            - ``"applied"`` — list of confirmed operation keys.
            - ``"operations"`` — ordered executable operation descriptions.
            - ``"completed_operations"`` — descriptions of confirmed writes.

        Raises:
            JTComError: If the session is not open.
            JTComPolicyError: If policy blocks a real apply, before backup or writes.
            JTComApplyError: If backup, a write, or verification fails. Includes
                confirmed operations, the original exception, and best-effort readback.
        """
        session = self._require_session()

        # --- Read and normalize current state ---
        current_vlans, current_ports = self._read_current_state(session)
        validate_desired_config(desired, current_ports)
        current_cfg = DeviceConfig.from_current(current_vlans, current_ports)
        current_n = normalize_device_config(current_cfg)
        desired_n = normalize_device_config(desired)
        current_per_port = build_current_per_port_from_vlans(
            current_vlans,
            [settings.port_id for settings in current_ports],
        )
        merged_desired_vlans = merge_port_vlan_membership_inputs(
            current_per_port,
            desired_n.vlans,
            desired_n.ports,
            known_vlan_ids=current_vlans,
            auto_create_referenced_vlans=self.policy.auto_create_referenced_vlans,
        )
        desired_plan_n = DeviceConfig(
            vlans=merged_desired_vlans,
            ports=desired_n.ports,
            metadata=dict(desired_n.metadata),
        )

        # --- Build plan ---
        plan = build_device_plan(
            current_n,
            desired_plan_n,
        )
        membership_plan = self._plan_vlan_membership(
            current_vlans,
            current_ports,
            desired_plan_n.vlans,
            policy=self.policy,
        )
        diff = render_effective_diff(current_n, desired_plan_n, membership_plan)
        violations = evaluate_device_policy(plan, self.policy) + membership_plan.violations
        if membership_plan.changed_ports or membership_plan.warnings or membership_plan.violations:
            diff["vlan_membership"] = {
                "changed_ports": membership_plan.changed_ports,
                "changed_vlans": membership_plan.changed_vlans,
                "warnings": membership_plan.warnings,
                "violations": membership_plan.violations,
                "before": serialize_membership_map(membership_plan.current_per_port),
                "after": serialize_membership_map(membership_plan.desired_per_port),
            }

        if violations and not check_mode:
            raise JTComPolicyError(violations)

        # Compile every executable payload before backup or the first write.
        # A blocked preview has no executable operations (some cannot be compiled).
        operations = [] if violations else compile_apply_operations(
            plan, desired_plan_n, current_ports, membership_plan,
        )
        operation_records = [operation.describe() for operation in operations]

        changed = (
            bool(plan.changes or membership_plan.changed_ports) if violations else bool(operations)
        )
        if check_mode or not changed:
            return {
                "changed": changed,
                "blocked": bool(violations),
                "violations": violations,
                "diff": diff,
                "backup_file": "",
                "applied": [],
                "operations": operation_records,
                "completed_operations": [],
                "warnings": membership_plan.warnings,
                "changed_ports": membership_plan.changed_ports,
                "changed_vlans": membership_plan.changed_vlans,
                "before": serialize_membership_map(membership_plan.current_per_port),
                "after": serialize_membership_map(membership_plan.desired_per_port),
            }

        # Verify membership against the effective canonical target, not by
        # replaying the original patch after policy fallback resolution.
        verification_desired = DeviceConfig(
            vlans={vid: VlanConfig(vid, name=cfg.name, state=cfg.state)
                   for vid, cfg in desired_plan_n.vlans.items()},
            ports=desired_plan_n.ports,
        )
        backup_file = ""
        completed: list[dict[str, str]] = []
        failed_operation = {"key": "backup", "kind": "backup"}
        write_attempted = False
        readback: dict[str, Any] | None = None
        try:
            if self.policy.backup_before_change:
                backup_file = self._save_backup(session, self.policy.backup_dir)

            for operation in operations:
                failed_operation = operation.describe()
                write_attempted = True
                session.post(operation.endpoint, data=deepcopy(operation.data))
                completed.append(operation.describe())
                logger.info("Applied %s (%s)", operation.key, operation.kind)

            failed_operation = {"key": "verify", "kind": "verification"}
            post_vlans, post_ports = self._read_current_state(session)
            readback = _serialize_readback(post_vlans, post_ports)
            post_cfg = DeviceConfig.from_current(post_vlans, post_ports)
            post_n = normalize_device_config(post_cfg)
            missing_ports = sorted(set(verification_desired.ports) - set(post_n.ports))
            if missing_ports:
                raise JTComVerificationError(remaining_diff={
                    "total_changes": len(missing_ports),
                    "changes": [{"kind": "port_missing", "key": f"port:{pid}",
                                 "details": {"port_id": pid}} for pid in missing_ports],
                })
            residual_plan = build_device_plan(post_n, verification_desired)
            if residual_plan.changes:
                raise JTComVerificationError(remaining_diff=render_diff(residual_plan))
            self._verify_vlan_membership(
                session, membership_plan, current_state=(post_vlans, post_ports),
            )
        except Exception as exc:
            readback_error: Exception | None = None
            if readback is None:
                try:
                    observed_vlans, observed_ports = self._read_current_state(session)
                    readback = _serialize_readback(observed_vlans, observed_ports)
                except Exception as recovery_exc:
                    readback_error = recovery_exc
            raise JTComApplyError(
                backup_file=backup_file,
                completed_operations=completed,
                failed_operation=failed_operation,
                original_exception=exc,
                write_attempted=write_attempted,
                readback=readback,
                readback_error=readback_error,
            ) from exc

        return {
            "changed": True,
            "blocked": False,
            "violations": [],
            "diff": diff,
            "backup_file": backup_file,
            "applied": [operation["key"] for operation in completed],
            "operations": operation_records,
            "completed_operations": completed,
            "warnings": membership_plan.warnings,
            "changed_ports": membership_plan.changed_ports,
            "changed_vlans": membership_plan.changed_vlans,
        }

    def _plan_vlan_membership(
        self,
        current_vlans: dict[int, VlanEntry],
        current_ports: list[PortSettings],
        desired_vlans: dict[int, VlanConfig],
        *,
        policy: ApplyPolicy,
    ) -> VlanMembershipPlan:
        """Build a canonical VLAN membership plan from current switch state."""
        known_ports = [settings.port_id for settings in current_ports]
        current_per_port = build_current_per_port_from_vlans(current_vlans, known_ports)
        return plan_vlan_membership_changes(
            current_per_port,
            desired_vlans.values(),
            allow_port_mode_change=policy.allow_port_mode_change,
            allow_untagged_move=policy.allow_untagged_move,
            allow_vlan_delete_in_use=policy.allow_vlan_delete_in_use,
        )

    def _apply_vlan_membership_plan(
        self,
        session: JTComSession,
        membership_plan: VlanMembershipPlan,
    ) -> None:
        """Compile the complete membership batch before issuing any writes."""
        for operation in compile_membership_operations(membership_plan):
            session.post(operation.endpoint, data=deepcopy(operation.data))

    def _verify_vlan_membership(
        self,
        session: JTComSession,
        membership_plan: VlanMembershipPlan,
        *,
        current_state: tuple[dict[int, VlanEntry], list[PortSettings]] | None = None,
    ) -> None:
        """Verify changed VLAN membership ports after a real apply.

        Expected state comes directly from the canonical plan. Actual state is
        read back from JTCom, normalized to canonical semantics, and compared
        without any backend-shaped reinterpretation.
        """
        if not membership_plan.changed_ports:
            return
        post_vlans, post_ports = (
            current_state if current_state is not None else self._read_current_state(session)
        )
        post_per_port = build_current_per_port_from_vlans(
            post_vlans,
            [settings.port_id for settings in post_ports],
        )
        expected: PortMembershipMap = {
            port_id: copy_port_state(membership_plan.desired_per_port[port_id])
            for port_id in membership_plan.changed_ports
        }
        actual: PortMembershipMap = {
            port_id: post_per_port.get(port_id, {"untagged_vlan": None, "tagged_vlans": set()})
            for port_id in membership_plan.changed_ports
        }
        remaining_diff = diff_membership_maps(actual, expected)
        if remaining_diff:
            raise JTComVerificationError(
                remaining_diff={
                    "total_changes": len(remaining_diff),
                    "changes": remaining_diff,
                }
            )

    def _fetch_vlan_state(self, session: JTComSession) -> dict[int, VlanEntry]:
        """Fetch static VLANs and port-based VLAN settings, merge into a map.

        Reads the static VLAN list and per-port VLAN configuration from the
        switch, normalizes JTCom backend trunk/access readback into canonical
        per-port membership semantics, then materializes :class:`VlanEntry`
        objects from that canonical state.

        Args:
            session: Active authenticated session.

        Returns:
            A ``dict[int, VlanEntry]`` keyed by VLAN ID with port memberships
            populated.
        """
        static_html = session.get(VLAN_STATIC, params={"page": "static"})
        port_html = session.get(VLAN_PORT_BASED, params={"page": "port_based"})
        vlans = parse_static_vlans(static_html)
        port_configs = parse_port_vlan_settings(port_html)

        vlan_map: dict[int, VlanEntry] = {v.vlan_id: v for v in vlans}
        for config in port_configs:
            references = [
                ("access_vlan", config.access_vlan),
                ("native_vlan", config.native_vlan),
                *(("permit_vlans", vid) for vid in config.permit_vlans),
            ]
            for field, vlan_id in references:
                if vlan_id is not None and vlan_id not in vlan_map:
                    raise JTComStateError(
                        f"VLAN readback: port={config.port_name!r} field={field} "
                        f"raw={vlan_id!r} references an unknown VLAN; "
                        f"known VLANs: {sorted(vlan_map)}"
                    )
            if config.vlan_type.lower() == "trunk" and (
                config.native_vlan not in config.permit_vlans
            ):
                raise JTComStateError(
                    f"VLAN readback: port={config.port_name!r} field=permit_vlans "
                    f"raw={config.permit_vlans!r} omits native VLAN {config.native_vlan!r}"
                )
        known_ports = [port_name_to_id(pc.port_name) for pc in port_configs]
        try:
            current_per_port = build_current_per_port_from_jtcom_readback(
                port_configs, known_ports,
            )
        except ValueError as exc:
            raise JTComStateError(f"Inconsistent VLAN readback: {exc}") from exc
        port_name_by_id = {
            port_name_to_id(pc.port_name): pc.port_name
            for pc in port_configs
        }
        for port_id, state in current_per_port.items():
            port_name = port_name_by_id[port_id]
            untagged_vlan = state["untagged_vlan"]
            if isinstance(untagged_vlan, int):
                vlan_map[untagged_vlan].untagged_ports.append(port_name)
            tagged_vlans = state["tagged_vlans"]
            if isinstance(tagged_vlans, set):
                for vid in sorted(tagged_vlans):
                    vlan_map[vid].tagged_ports.append(port_name)
        return vlan_map

    def _read_current_state(
        self, session: JTComSession
    ) -> tuple[dict[int, VlanEntry], list[PortSettings]]:
        """Read VLANs and ports from the switch and return both.

        Args:
            session: Active authenticated session.

        Returns:
            A tuple of ``(vlan_map, settings_list)`` where ``vlan_map`` is a
            ``dict[int, VlanEntry]`` (with port memberships populated) and
            ``settings_list`` is a ``list[PortSettings]``.
        """
        vlan_map = self._fetch_vlan_state(session)

        port_html2 = session.get(PORT_SETTINGS)
        settings_list, _ = parse_port_page(port_html2)
        setting_ids = {settings.port_id for settings in settings_list}
        membership_ids = {
            port_name_to_id(name)
            for vlan in vlan_map.values()
            for name in vlan.tagged_ports + vlan.untagged_ports
        }
        if setting_ids != membership_ids:
            raise JTComStateError(
                "Inconsistent port inventory across port settings and VLAN pages: "
                f"missing VLAN rows for ports {sorted(setting_ids - membership_ids)}; "
                f"unknown VLAN-page ports {sorted(membership_ids - setting_ids)}"
            )
        return vlan_map, settings_list

    def _save_backup(
        self, session: JTComSession, backup_dir: str | pathlib.Path = "./backups"
    ) -> str:
        """Download a config backup and save it to disk.

        Args:
            session: Active authenticated session.

        Returns:
            The local file path of the saved backup.
        """
        backup_dir = pathlib.Path(str(backup_dir))
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_host = self.hostname.replace("://", "_").replace("/", "_").replace(":", "_")
        filename = f"jtcom_{safe_host}_{ts}_switch_cfg.bin"
        backup_path = backup_dir / filename
        raw = session.download_config_backup()
        backup_path.write_bytes(raw)
        logger.info("Config backup saved to %s (%d bytes)", backup_path, len(raw))
        return str(backup_path)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_base_url(self) -> str:
        """Construct the switch base URL from hostname / port / TLS settings."""
        if "://" in self.hostname:
            return self.hostname.rstrip("/")
        scheme = "https" if self._verify_tls else "http"
        host = self.hostname
        port = self._port
        default_port = 443 if self._verify_tls else 80
        if port == default_port:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"

    def _require_session(self) -> JTComSession:
        """Return the active session or raise :exc:`.JTComError`."""
        if self._session is None:
            raise JTComError("Session not open — call open() first.")
        return self._session


def _serialize_readback(
    vlans: dict[int, VlanEntry], ports: list[PortSettings],
) -> dict[str, Any]:
    """Capture a detached snapshot before verification can fail."""
    return {
        "vlans": {vid: asdict(vlan) for vid, vlan in sorted(vlans.items())},
        "ports": [asdict(port) for port in sorted(ports, key=lambda port: port.port_id)],
    }
