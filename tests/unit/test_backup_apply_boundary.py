"""Invalid backup bodies cannot reach disk or the apply write phase."""

from pathlib import Path

import pytest
import responses

from cgiswitch import ApplyPolicy, JTComApplyError, JTComSwitch
from cgiswitch.client.errors import JTComParseError
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig, VlanEntry


@pytest.mark.parametrize("body", [b"", b"<html><body>Error</body></html>"])
@responses.activate
def test_invalid_backup_is_not_saved_and_blocks_apply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes,
) -> None:
    base = "http://192.0.2.1"
    session = JTComSession(base, JTComCredentials("admin", "secret"))
    session._logged_in = True
    responses.add(responses.GET, base + "/config.cgi", body=body)
    switch = JTComSwitch("192.0.2.1", "admin", "secret", policy=ApplyPolicy(backup_dir=tmp_path))
    switch._session = session
    monkeypatch.setattr(switch, "_read_current_state", lambda _: ({1: VlanEntry(1, "default")}, []))
    with pytest.raises(JTComApplyError) as captured:
        switch.apply(DeviceConfig(vlans={20: VlanConfig(20, "new")}))
    assert isinstance(captured.value.original_exception, JTComParseError)
    assert captured.value.failed_operation["kind"] == "backup"
    assert captured.value.backup_file == ""
    assert captured.value.write_attempted is False
    assert list(tmp_path.iterdir()) == []
    assert [call.request.method for call in responses.calls] == ["GET"]
