"""Low-level HTTP utilities (private)."""
from typing import Any, Dict, Optional
import json
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
    """
    Standardized HTTP wrapper returning:
      {
        "status_code": int,
        "data": Any,
        "error": Optional[str]
      }

    Behavior:
    - When expect_json=True:
        * Parse JSON; on failure, surface a structured non-JSON payload sample.
        * For error HTTP codes, attempt to pass through controller-provided error fields.
    - When expect_json=False:
        * Return raw text in 'data'.
    """
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

    # Non-JSON mode: return raw text body.
    if not expect_json:
        return {
            "status_code": response.status_code,
            "data": response.text,
            "error": None if response.ok else (response.reason or "error"),
        }

    # JSON mode: try to parse; if it fails, provide a structured sample.
    text = response.text or ""
    try:
        payload = response.json()
        # Parsed JSON
        if response.ok:
            # If the server already returned our standard envelope, pass it through.
            if isinstance(payload, dict) and {"status_code", "data", "error"} <= set(payload.keys()):
                return payload
            return {"status_code": response.status_code, "data": payload, "error": None}

        # Prefer common fields from controllers.
        if isinstance(payload, dict):
            # If server already returned our standard envelope, pass it through
            # but strip the inner controller 'error' to avoid duplication.
            if {"status_code", "data", "error"} <= set(payload.keys()):
                inner = payload.get("data")
                if isinstance(inner, dict) and "body_sample" in inner and "error" in inner:
                    inner = dict(inner)
                    inner.pop("error", None)          # <-- remove duplicated inner error
                    payload = dict(payload)
                    payload["data"] = inner
                return payload

            message = (
                payload.get("error")
                or payload.get("message")
                or payload.get("detail")
                or payload.get("title")
                or response.reason
                or "error"
            )
            return {"status_code": response.status_code, "data": payload, "error": message}

        # JSON but not a dict (e.g., string/array) — still pass through.
        return {
            "status_code": response.status_code,
            "data": payload,
            "error": response.reason or "error",
        }

    except ValueError:
        # Non-JSON response body (often HTML or plain text with embedded JSON error)
        body_sample = text[:1000]
        if response.ok:
            return {
                "status_code": response.status_code,
                "data": {"body_sample": body_sample},
                "error": "Non-JSON success",
            }

        # Try to parse embedded JSON if body looks like JSON stringified text.
        embedded: Optional[Any] = None
        trimmed = body_sample.strip()
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (
            trimmed.startswith("[") and trimmed.endswith("]")
        ):
            try:
                embedded = json.loads(trimmed)
            except Exception:
                embedded = None

        # Build a consistent non-JSON error structure.
        data_obj: Dict[str, Any] = {
            "status_code": response.status_code,
            "error": "Non-JSON error response",
            "body_sample": body_sample,
        }
        if embedded is not None:
            data_obj["embedded"] = embedded

        return {
            "status_code": response.status_code,
            "data": data_obj,
            "error": "Non-JSON error response",
        }

