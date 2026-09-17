"""Internal one-shot credential transport using the observed UI contract."""

from cgiswitch.client.errors import JTComRequestError
from cgiswitch.client.management_contracts import build_user_account_payload
from cgiswitch.client.session import JTComSession
from cgiswitch.vendor.jtcom.endpoints import USER_ACCOUNT


def change_password_once(session: JTComSession, username: str, password: str) -> None:
    """Send one account update; caller verifies identity and new authentication."""
    payload = build_user_account_payload(username, password)
    try:
        session._post_once(USER_ACCOUNT, payload)
    except JTComRequestError:
        raise JTComRequestError(
            USER_ACCOUNT, RuntimeError("Credential request transport failed"),
        ) from None
