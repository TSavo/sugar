# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

from typing import Any, Mapping, Optional


def fetch_event_response(
    method: str,
    endpoint: str,
    hdrs: Optional[Mapping[str, str]],
    body: Optional[Any],
):
    import requests
    kwargs = {"headers": hdrs, "data": body}
    return requests.request(method, endpoint, **kwargs)


def fetch_event_status(endpoint: str) -> int:
    import requests
    response = requests.get(endpoint)
    return response.status_code
