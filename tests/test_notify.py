import httpx
import respx

from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.notify import send_notification

URL = "http://notify.test/hook"


def _summary(drift: bool = False) -> SyncSummary:
    s = SyncSummary()
    if drift:
        s.albums_created = 1
    return s


@respx.mock
def test_sends_payload() -> None:
    route = respx.post(URL).respond(200)
    result = send_notification(URL, _summary(drift=True))
    assert result is True
    assert route.called
    req = route.calls[0].request
    assert b"albums_created" in req.content


@respx.mock
def test_drift_only_skips_no_drift() -> None:
    respx.post(URL).respond(200)
    result = send_notification(URL, _summary(drift=False), drift_only=True)
    assert result is False
    assert respx.calls.call_count == 0


@respx.mock
def test_drift_only_sends_on_drift() -> None:
    respx.post(URL).respond(200)
    result = send_notification(URL, _summary(drift=True), drift_only=True)
    assert result is True


@respx.mock
def test_network_error_returns_false() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("timeout"))
    result = send_notification(URL, _summary(drift=True))
    assert result is False


@respx.mock
def test_http_error_returns_false() -> None:
    respx.post(URL).respond(500)
    result = send_notification(URL, _summary(drift=True))
    assert result is False
