"""Resolve public targets through the proxy, not the isolated browser network."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

try:
    from .url_policy import URLNotAllowed, public_url
except ImportError:
    from url_policy import URLNotAllowed, public_url

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def checked_target(url: str):
    target = public_url(url, resolve=False)
    request = urllib.request.Request(
        "http://egress:8081/policy",
        data=json.dumps({"url": target.url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=10) as response:
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                raise ValueError()
            payload = json.loads(body)
            if payload != {"url": target.url}:
                raise ValueError()
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 403:
            raise URLNotAllowed("The egress policy refused the resolved destination.") from None
        raise ValueError("app-not-ready: the public-web policy service is unavailable") from None
    except (OSError, ValueError, urllib.error.URLError):
        raise ValueError("app-not-ready: the public-web policy service is unavailable") from None
    return target
