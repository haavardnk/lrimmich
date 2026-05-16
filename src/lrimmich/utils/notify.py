import httpx

from lrimmich.sync.orchestrator import SyncSummary


def send_notification(
    url: str,
    summary: SyncSummary,
    drift_only: bool = False,
) -> bool:
    if drift_only and not summary.has_drift:
        return False
    payload = summary.to_dict()
    try:
        resp = httpx.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except (httpx.HTTPError, httpx.TimeoutException):
        return False
