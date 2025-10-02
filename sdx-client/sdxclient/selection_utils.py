# selection_utils.py
"""Helpers for SDXClient: endpoint selection and L2VPN payload building.

Contract:
- Listing:
  - /available_ports (JSON) with either ?filter= (plain substring) or ?search= (key:value).
  - If both are present, filter wins (caller decides which to send).
- Matching:
  - Rows are expected to include spec fields: id, name, node, entities, status, state.
  - Ambiguity policy (for filter/search text): the caller may ask for all matches.
- Device info:
  - /device_info?port_id=...&format=json returns a single-port view used to pick a VLAN.
- Payload:
  - Build payload including both port_id and vlan for each endpoint.
"""

from typing import Any, Dict, List, Optional
from .http import _http_request


# ---- Available ports ----

def _list_available_ports_json(client, query_text: Optional[str], *, use_filter: bool) -> Dict[str, Any]:
    """Fetch /available_ports with JSON output, using either ?filter= or ?search=."""
    params: Dict[str, str] = {"format": "json"}
    if query_text:
        if use_filter:
            params["filter"] = query_text
        else:
            params["search"] = query_text
    return _http_request(
        client.session, client.base_url, "GET", "/available_ports",
        params=params, accept="application/json",
        timeout=client.timeout, expect_json=True,
    )


def _extract_rows_list(payload: Any) -> List[dict]:
    """Extract the list of port rows from the /available_ports JSON response."""
    if isinstance(payload, dict):
        return payload.get("ports") or []
    if isinstance(payload, list):
        return payload
    return []


def _find_matching_rows(rows: List[dict], search_text: str) -> List[dict]:
    """
    Return all rows that match the search_text across spec fields.
    Case-insensitive substring match across: id, name, node, entities, status, state.
    """
    if not search_text:
        return []
    normalized_search = search_text.strip().lower()
    matches: List[dict] = []
    for row in rows:
        for field_name in ("id", "name", "node", "entities", "status", "state"):
            field_value = row.get(field_name)
            if isinstance(field_value, list):
                if any(normalized_search in str(entry).lower() for entry in field_value):
                    matches.append(row)
                    break
            elif isinstance(field_value, str) and normalized_search in field_value.lower():
                matches.append(row)
                break
    return matches


# ---- Device info ----

def _fetch_device_info_by_port_id(client, port_id: str) -> Dict[str, Any]:
    """Fetch device information for a specific port URN (port_id)."""
    params: Dict[str, str] = {"port_id": port_id, "format": "json"}
    return _http_request(
        client.session, client.base_url, "GET", "/device_info",
        params=params, accept="application/json",
        timeout=client.timeout, expect_json=True,
    )


def _choose_vlan_from_device_info(device_info: Dict[str, Any], prefer_untagged: bool = False) -> Optional[str]:
    """
    Pick a VLAN from the /device_info response:
    - If prefer_untagged and 'untagged' is available, return it.
    - Otherwise return the first available VLAN token.
    """
    ports = device_info.get("ports") or []
    if not ports:
        return None

    # Expect one port when filtered by port_id
    port_row = ports[0]
    available_vlans_field = str(port_row.get("VLANs Available") or "").lower()
    if not available_vlans_field or available_vlans_field == "none":
        return None

    if prefer_untagged and "untagged" in available_vlans_field:
        return "untagged"

    first_token = available_vlans_field.split(",")[0].strip()
    return first_token if first_token else None
