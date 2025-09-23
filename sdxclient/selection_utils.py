"""Private helpers for listing, setting, and payload shaping (not user-facing)."""
from typing import Any, Dict, List, Optional

from .http import _http_request


# ------------------ Pure helpers (no network) ------------------

def _extract_rows_list(payload: Any) -> List[Dict[str, Any]]:
    """Extract table rows from common JSON shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _pick_row(rows: List[Dict[str, Any]], *, min_filter: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pick the first matching row by a simple substring filter over common columns."""
    if not rows:
        return None
    if not min_filter:
        return rows[0]
    needle = min_filter.lower().strip()
    columns = ("Domain", "Device", "Port", "Port ID", "Entities", "Status", "device", "port_id", "id")
    for row in rows:
        haystack = " ".join(str(row.get(k, "")) for k in columns).lower()
        if needle in haystack:
            return row
    return None


def _choose_vlan_from_device_info(info: Any, *, prefer_untagged: bool) -> Optional[str]:
    """Choose a VLAN from a device_info response (strings or ints accepted)."""
    if not isinstance(info, dict):
        return None

    # 1) Lists of options
    for key in ("available_vlans", "vlans", "vlans_available", "vlan_options"):
        value = info.get(key)
        if isinstance(value, list) and value:
            normalized = [str(v) for v in value if v is not None]
            if prefer_untagged and any(v.lower() == "untagged" for v in normalized):
                return "untagged"
            for v in normalized:
                if v.isdigit():
                    return v
            return normalized[0]

    # 2) Single suggestion
    for key in ("suggested_vlan", "vlan", "default_vlan"):
        value = info.get(key)
        if value is not None:
            return str(value)

    # 3) Nested dicts
    for key in ("port", "endpoint", "details"):
        nested = info.get(key)
        vlan = _choose_vlan_from_device_info(nested, prefer_untagged=prefer_untagged)
        if vlan:
            return vlan

    return None


def _build_l2vpn_payload(
    *,
    name: str,
    notifications: str,
    first_endpoint: Dict[str, Any],
    second_endpoint: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "name": name,
        "endpoints": [
            {"port_id": first_endpoint["port_id"], "vlan": first_endpoint["vlan"]},
            {"port_id": second_endpoint["port_id"], "vlan": second_endpoint["vlan"]},
        ],
        "Notifications": notifications,
    }


# --------------- Stateful helpers (operate on client) ----------------

def _begin_selection_state(client: Any) -> Dict[str, Any]:
    client._first_endpoint = None
    client._second_endpoint = None
    client._last_first_rows = None
    client._last_second_rows = None
    client._last_first_info = None
    client._last_second_info = None
    return {"status_code": 200, "data": True, "error": None}


def _get_selected_endpoints(client: Any) -> Dict[str, Any]:
    return {
        "status_code": 200,
        "data": {"first": client._first_endpoint, "second": client._second_endpoint},
        "error": None,
    }


def _get_first_endpoints(client: Any, search: Optional[str], limit: int, *, format: str) -> Dict[str, Any]:
    """Return HTML or JSON and cache JSON rows for subsequent set_* calls."""
    params: Dict[str, Any] = {
        "format": format,
        "fields": "Domain,Device,Port,Status,Port ID,Entities",
        "limit": str(limit),
    }
    if search:
        params["search"] = search

    accept = "text/html" if format == "html" else "application/json"
    expect_json = format != "html"

    result = _http_request(
        client.session, client.base_url, "GET", "/available_ports",
        params=params, accept=accept, timeout=client.timeout, expect_json=expect_json,
    )

    # Cache rows when JSON arrived
    if format == "json" and result["status_code"] == 200 and isinstance(result["data"], (dict, list)):
        data = result["data"]
        rows = _extract_rows_list(data)
        client._last_first_rows = rows

    elif format == "html":
        # Also fetch JSON silently to fill cache for set_* calls,
        # but only if we actually have a bearer token and no auth error.
        auth_header = client.session.headers.get("Authorization", "")
        have_bearer = isinstance(auth_header, str) and auth_header.startswith("Bearer ")
        if have_bearer and not getattr(client, "auth_error", None):
            params_json = dict(params)
            params_json["format"] = "json"
            json_result = _http_request(
                client.session, client.base_url, "GET", "/available_ports",
                params=params_json, accept="application/json", timeout=client.timeout, expect_json=True,
            )
            if json_result["status_code"] == 200 and isinstance(json_result["data"], (dict, list)):
                client._last_first_rows = _extract_rows_list(json_result["data"])
            else:
                client._last_first_rows = None
        else:
            client._last_first_rows = None

    return result


def _get_second_endpoints(client: Any, search: Optional[str], limit: int, *, format: str) -> Dict[str, Any]:
    """Return HTML or JSON and cache JSON rows for subsequent set_* calls (includes VLANs in Use)."""
    params: Dict[str, Any] = {
        "format": format,
        "fields": "Domain,Device,Port,Status,Port ID,Entities,VLANs in Use",
        "limit": str(limit),
    }
    if search:
        params["search"] = search

    accept = "text/html" if format == "html" else "application/json"
    expect_json = format != "html"

    result = _http_request(
        client.session, client.base_url, "GET", "/available_ports",
        params=params, accept=accept, timeout=client.timeout, expect_json=expect_json,
    )

    # Cache rows when JSON arrived
    if format == "json" and result["status_code"] == 200 and isinstance(result["data"], (dict, list)):
        data = result["data"]
        rows = _extract_rows_list(data)
        client._last_second_rows = rows

    elif format == "html":
        # Also fetch JSON silently to fill cache for set_* calls,
        # but only if we actually have a bearer token and no auth error.
        auth_header = client.session.headers.get("Authorization", "")
        have_bearer = isinstance(auth_header, str) and auth_header.startswith("Bearer ")
        if have_bearer and not getattr(client, "auth_error", None):
            params_json = dict(params)
            params_json["format"] = "json"
            json_result = _http_request(
                client.session, client.base_url, "GET", "/available_ports",
                params=params_json, accept="application/json", timeout=client.timeout, expect_json=True,
            )
            if json_result["status_code"] == 200 and isinstance(json_result["data"], (dict, list)):
                client._last_second_rows = _extract_rows_list(json_result["data"])
            else:
                client._last_second_rows = None
        else:
            client._last_second_rows = None

    return result


def _set_first_endpoint(client: Any, min_filter: Optional[str], prefer_untagged: Optional[bool]) -> Dict[str, Any]:
    if getattr(client, "auth_error", None):
        return {"status_code": 0, "data": None, "error": f"auth not ready: {client.auth_error}"}
    if not client._last_first_rows:
        return {"status_code": 0, "data": None, "error": "no first endpoints listed; call get_first_endpoints() first"}

    chosen = _pick_row(client._last_first_rows, min_filter=min_filter)
    if not chosen:
        return {"status_code": 0, "data": None, "error": "no matching first endpoint"}

    port_id = str(chosen.get("Port ID") or chosen.get("port_id") or chosen.get("id") or "").strip()
    if not port_id:
        return {"status_code": 0, "data": None, "error": "row missing Port ID"}

    info_result = client._fetch_device_info_by_port_id(port_id=port_id)
    if info_result["status_code"] != 200:
        return info_result

    client._last_first_info = info_result["data"] if isinstance(info_result["data"], dict) else None
    vlan_choice = _choose_vlan_from_device_info(client._last_first_info, prefer_untagged=bool(prefer_untagged))
    if not vlan_choice:
        return {"status_code": 0, "data": None, "error": "no usable VLAN found for first endpoint"}

    client._first_endpoint = {"port_id": port_id, "vlan": str(vlan_choice)}
    return {"status_code": 200, "data": client._first_endpoint, "error": None}


def _set_second_endpoint(client: Any, min_filter: Optional[str], prefer_untagged: Optional[bool]) -> Dict[str, Any]:
    if getattr(client, "auth_error", None):
        return {"status_code": 0, "data": None, "error": f"auth not ready: {client.auth_error}"}
    if not client._last_second_rows:
        return {"status_code": 0, "data": None, "error": "no second endpoints listed; call get_second_endpoints() first"}

    chosen = _pick_row(client._last_second_rows, min_filter=min_filter)
    if not chosen:
        return {"status_code": 0, "data": None, "error": "no matching second endpoint"}

    port_id = str(chosen.get("Port ID") or chosen.get("port_id") or chosen.get("id") or "").strip()
    if not port_id:
        return {"status_code": 0, "data": None, "error": "row missing Port ID"}

    info_result = client._fetch_device_info_by_port_id(port_id=port_id)
    if info_result["status_code"] != 200:
        return info_result

    client._last_second_info = info_result["data"] if isinstance(info_result["data"], dict) else None
    vlan_choice = _choose_vlan_from_device_info(client._last_second_info, prefer_untagged=bool(prefer_untagged))
    if not vlan_choice:
        return {"status_code": 0, "data": None, "error": "no usable VLAN found for second endpoint"}

    client._second_endpoint = {"port_id": port_id, "vlan": str(vlan_choice)}
    return {"status_code": 200, "data": client._second_endpoint, "error": None}


def _set_first_endpoint_by_port_id(client: Any, port_id: str, prefer_untagged: bool) -> Dict[str, Any]:
    if getattr(client, "auth_error", None):
        return {"status_code": 0, "data": None, "error": f"auth not ready: {client.auth_error}"}
    info_result = client._fetch_device_info_by_port_id(port_id=port_id)
    if info_result["status_code"] != 200:
        return info_result
    client._last_first_info = info_result["data"] if isinstance(info_result["data"], dict) else None
    vlan_choice = _choose_vlan_from_device_info(client._last_first_info, prefer_untagged=prefer_untagged)
    if not vlan_choice:
        return {"status_code": 0, "data": None, "error": "no usable VLAN found for first endpoint"}
    client._first_endpoint = {"port_id": port_id, "vlan": str(vlan_choice)}
    return {"status_code": 200, "data": client._first_endpoint, "error": None}


def _set_second_endpoint_by_port_id(client: Any, port_id: str, prefer_untagged: bool) -> Dict[str, Any]:
    if getattr(client, "auth_error", None):
        return {"status_code": 0, "data": None, "error": f"auth not ready: {client.auth_error}"}
    info_result = client._fetch_device_info_by_port_id(port_id=port_id)
    if info_result["status_code"] != 200:
        return info_result
    client._last_second_info = info_result["data"] if isinstance(info_result["data"], dict) else None
    vlan_choice = _choose_vlan_from_device_info(client._last_second_info, prefer_untagged=prefer_untagged)
    if not vlan_choice:
        return {"status_code": 0, "data": None, "error": "no usable VLAN found for second endpoint"}
    client._second_endpoint = {"port_id": port_id, "vlan": str(vlan_choice)}
    return {"status_code": 200, "data": client._second_endpoint, "error": None}

