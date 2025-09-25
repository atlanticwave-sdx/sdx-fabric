"""Low-level HTTP utilities (private)."""
from typing import Any, Dict, Optional
import requests


def _http_request(
    session: requests.Session,
    base_url: str,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    accept: Optional[str] = None,
    timeout: float = 6.0,
    expect_json: bool = True,
) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    try:
        headers: Dict[str, str] = {}
        if accept:
            headers["Accept"] = accept
        response = session.request(
            method=method.upper(),
            url=url,
            params=params,
            json=json_body,
            headers=headers or None,
            timeout=timeout,
        )
    except requests.Timeout:
        return {"status_code": 0, "data": None, "error": "timeout"}
    except requests.RequestException as exc:
        return {"status_code": 0, "data": None, "error": f"network error: {exc}"}

    if not expect_json:
        return {
            "status_code": response.status_code,
            "data": response.text,
            "error": None if response.ok else response.reason,
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "data": None,
            "error": response.text[:200] if response.text else response.reason,
        }

    return {
        "status_code": response.status_code,
            # If server returns a JSON string, still pass it as data.
        "data": payload,
        "error": None if response.ok else (payload if isinstance(payload, str) else response.reason),
    }

