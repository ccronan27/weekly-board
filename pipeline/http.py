"""One shared HTTP session with retries. Generic client name only."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = 60
_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers["User-Agent"] = "weekly-board/1.0"
        _session = s
    return _session


def get(url: str, params=None, headers=None) -> requests.Response:
    r = session().get(url, params=params, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def get_json(url: str, params=None, headers=None):
    return get(url, params, headers).json()
