"""Bounded GET retries for transient gateways; digest mismatches never retry."""
from __future__ import annotations

import hashlib
import http.client
import time
import threading
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

_thread_http = threading.local()


def opener():
    # A fresh urllib opener also creates an HTTPS handler/SSL context, even for
    # HTTP URLs. Handler-parent cycles can retain native certificate stores
    # across a large batch. Bound that memory to one opener per worker thread.
    if not hasattr(_thread_http, 'opener'):
        _thread_http.opener = build_opener(ProxyHandler({}))
    return _thread_http.opener


def verify_url(url: str, expected_sha256: str, *, attempts: int = 3) -> int:
    """Verify the complete response and return the number of transient retries."""
    if attempts < 1:
        raise ValueError('positive HTTP attempt count required')
    for attempt in range(attempts):
        try:
            hasher = hashlib.sha256()
            with opener().open(url, timeout=30) as response:
                if response.status != 200:
                    raise ValueError('unexpected HTTP status: ' + str(response.status))
                for block in iter(lambda: response.read(256 * 1024), b''):
                    hasher.update(block)
                if response.length not in (None, 0):
                    raise http.client.IncompleteRead(b'', response.length)
            if hasher.hexdigest() != expected_sha256:
                raise ValueError('HTTP digest mismatch: ' + url)
            return attempt
        except HTTPError as exc:
            exc.close()
            if exc.code not in (429, 502, 503, 504) or attempt + 1 == attempts:
                raise
        except (OSError, URLError, http.client.HTTPException):
            if attempt + 1 == attempts:
                raise
        time.sleep(.25 * (2 ** attempt))
    raise RuntimeError('unreachable HTTP retry state')
