import time
import requests
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def retry_with_backoff(
    func, max_attempts: int = 3, base_delay: float = 2.0, max_delay: float = 30.0
):
    for attempt in range(max_attempts):
        try:
            return func()
        except (requests.exceptions.RequestException, TimeoutError) as e:
            response = getattr(e, "response", None)
            response_text = ""
            if response is not None and response.text:
                response_text = f" Response body: {response.text[:500]}"
            if attempt == max_attempts - 1:
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                f"Request failed (attempt {attempt + 1}/{max_attempts}), "
                f"retrying in {delay}s: {e}{response_text}"
            )
            time.sleep(delay)


def safe_request(
    method: str, url: str, headers: Optional[dict] = None, **kwargs
) -> Optional[requests.Response]:
    def _make_request():
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    try:
        return retry_with_backoff(_make_request)
    except requests.exceptions.RequestException as e:
        response = getattr(e, "response", None)
        response_text = ""
        if response is not None and response.text:
            response_text = f" Response body: {response.text[:500]}"
        logger.error(f"Request failed after retries: {url} - {e}{response_text}")
        return None


HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
