"""
Lightweight, local validators used by sdxclient.

VLAN Rules (per spec):
- Allowed forms:
  * Numeric VLANs (1..4095)
  * Ranges "A:B" with 1 <= A < B <= 4095
  * Keywords: "any", "untagged"
  * NOTE: "all" is NOT allowed

- Mixing:
  * Numeric ↔ Range (e.g., 200 with 100:300) ✓
  * any ↔ untagged ✓
  * any/untagged mixed with numeric/range ✓
  * "all" with anything ✗

- Rejection:
  * Same numeric VLAN twice (e.g., 200 & 200) ✗
  * Same exact range twice (e.g., 100:200 & 100:200) ✗
"""

import re
from typing import Any, Dict, List, Optional, Union

# ---------- basic constants ----------

PORT_ID_PATTERN = r"^urn:sdx:port:[a-zA-Z0-9.,\-_/]+:[a-zA-Z0-9.,\-_/]+:[a-zA-Z0-9.,\-_/]+$"
ALLOWED_SPECIAL_VLANS = {"any", "untagged"}  # "all" is intentionally NOT allowed

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---------- simple checks ----------
def _missing_params(**pairs: Any) -> Optional[str]:
    """Return a 'missing required parameter(s): a, b' message or None."""
    missing_parameters = [name for name, value in pairs.items() if value in (None, "", [])]
    return f"missing required parameter(s): {', '.join(missing_parameters)}" if missing_parameters else None

def _validate_name(name: Optional[str]) -> str:
    """Non-empty <= 50 chars."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string.")
    if len(name) > 50:
        raise ValueError("name must be at most 50 characters.")
    return name

def _validate_notifications(
        notifications: Union[str, Dict[str, str], List[Union[str, Dict[str, str]]], None]
    ) -> List[Dict[str, str]]:
    """
    Normalize and validate notifications input.

    Accepted inputs:
      - str: "info@example.com"
      - list[str]: ["info1@example.com", "info2@example.com"]
      - dict: {"email": "info@example.com"}
      - list[dict]: [{"email": "info@example.com"}, {"email": "info2@example.com"}]

    Rules:
      - Accepts str, list[str], dict{"email": str}, or list[dict{"email": str}].
      - Validates with EMAIL_REGEX.
      - Always returns a list (possibly empty).
      - If >10 valid entries after normalization → returns [] (no truncation).

    Returns:
      - list[dict]: [{"email": "<valid>"}] (0..10 entries; invalid inputs skipped)
      - [] if input is None, empty, not a supported type, or >10 valid emails.
    """

    if notifications is None:
        return []

    if isinstance(notifications, dict):
        notifications = [notifications]
    elif isinstance(notifications, str):
        notifications = [notifications]

    if not isinstance(notifications, list):
        return []

    normalized_emails: List[Dict[str, str]] = []
    for candidate in notifications:
        email_value: str = ""
        if isinstance(candidate, str):
            email_value = candidate.strip()
        elif isinstance(candidate, dict):
            email_value = str(candidate.get("email", "")).strip()

        if email_value and EMAIL_REGEX.match(email_value):
            normalized_emails.append({"email": email_value})

    if len(normalized_emails) == 0:
        return []
    if len(normalized_emails) > 10:
        return []

    return normalized_emails

# ---------- VLAN / endpoint validation ----------

def _validate_vlan_range(text: str) -> str:
    """Accept 'A:B' where 1 <= A < B <= 4095."""
    try:
        left, right = map(int, text.split(":"))
    except Exception:
        raise ValueError(f"invalid VLAN range '{text}'; expected 'A:B' with integers.")
    if not (1 <= left < right <= 4095):
        raise ValueError("VLAN range values must satisfy 1 <= A < B <= 4095.")
    return f"{left}:{right}"  # normalized

def _normalize_vlan_token(vlan: Union[str, int]) -> Dict[str, str]:
    """
    Classify and normalize a VLAN token for comparison rules.
    Returns {"kind": "special"|"numeric"|"range", "value": "<normalized>"}.
    """
    if isinstance(vlan, int):
        if 1 <= vlan <= 4095:
            return {"kind": "numeric", "value": str(vlan)}
        raise ValueError("VLAN must be between 1 and 4095.")
    if not isinstance(vlan, str) or not vlan.strip():
        raise ValueError("endpoint requires 'vlan' as non-empty string or int.")

    v = vlan.strip().lower()
    if v == "all":
        raise ValueError("VLAN keyword 'all' is not allowed.")
    if v in ALLOWED_SPECIAL_VLANS:
        return {"kind": "special", "value": v}
    if v.isdigit():
        vid = int(v)
        if 1 <= vid <= 4095:
            return {"kind": "numeric", "value": str(vid)}
        raise ValueError("VLAN must be between 1 and 4095.")
    if ":" in v:
        return {"kind": "range", "value": _validate_vlan_range(v)}
    raise ValueError("vlan must be 'any'|'untagged', a number (1..4095), or a range 'A:B'.")

def _validate_endpoint_dict(endpoint: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate one endpoint shape:
      - port_id matches URN format
      - vlan follows allowed forms (no 'all')
    Returns normalized dict with strings.
    """
    if not isinstance(endpoint, dict):
        raise TypeError("endpoint must be a dict.")
    port_id = endpoint.get("port_id")
    if not isinstance(port_id, str) or not re.match(PORT_ID_PATTERN, port_id):
        raise ValueError(f"invalid port_id format: {port_id}")

    vlan_norm = _normalize_vlan_token(endpoint.get("vlan"))
    return {"port_id": port_id, "vlan": vlan_norm["value"]}

def _validate_endpoints(endpoints: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """
    Endpoint-level policy (per latest rules):
      - Require at least two endpoints.
      - ALLOW mixing (numeric↔range, special↔numeric/range, any↔untagged).
      - REJECT ONLY:
          * same numeric VLAN token twice (e.g., 200 & 200)
          * same exact range twice (e.g., 100:200 & 100:200)
      - 'all' is not permitted anywhere.
    Returns the normalized endpoints list.
    """
    if not isinstance(endpoints, list) or len(endpoints) < 2:
        raise ValueError("endpoints must be a list with at least 2 entries.")

    normalized: List[Dict[str, str]] = []
    kinds_values: List[Dict[str, str]] = []

    for ep in endpoints:
        norm = _validate_endpoint_dict(ep)
        normalized.append(norm)
        kv = _normalize_vlan_token(norm["vlan"])  # classify after normalization
        kinds_values.append(kv)

    # Enforce rejection rules across all pairs
    seen_numeric: set[str] = set()
    seen_ranges: set[str] = set()
    for kv in kinds_values:
        if kv["kind"] == "numeric":
            if kv["value"] in seen_numeric:
                raise ValueError(f"endpoints cannot use the same numeric VLAN ({kv['value']}) twice.")
            seen_numeric.add(kv["value"])
        elif kv["kind"] == "range":
            if kv["value"] in seen_ranges:
                raise ValueError(f"endpoints cannot use the same VLAN range ({kv['value']}) twice.")
            seen_ranges.add(kv["value"])
        # specials (any/untagged) can repeat; allowed per spec

    return normalized

