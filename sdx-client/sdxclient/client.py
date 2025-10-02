"""Stateful thin client (user-facing) aligned with AW-SDX 2.0 Topology Data Model."""
from typing import Any, Dict, Optional, List, Union
import requests

from .config import BASE_URL
from .fablib_token import _load_fabric_token
from .http import _http_request
from .selection_utils import (
    _choose_vlan_from_device_info,
    _extract_rows_list,
    _find_matching_rows,           # matcher for available_ports rows
    _list_available_ports_json,
    _fetch_device_info_by_port_id,
)
from .validator import (
    _missing_params,
    _validate_name,
    _validate_notifications,
    _validate_endpoint_dict,
    _validate_endpoints,
)

# ---------------------------
# API guard + small utilities
# ---------------------------

def _api_guard(target_function):
    """Ensure a consistent dict response even on unexpected errors."""
    def wrapper(*args, **kwargs):
        try:
            output = target_function(*args, **kwargs)
            # Normalize accidental non-dict returns.
            if not isinstance(output, dict) or not {"status_code", "data", "error"} <= set(output.keys()):
                return {"status_code": 0, "data": None, "error": "internal error: invalid return shape"}
            return output
        except Exception as exception:  # noqa: BLE001
            return {"status_code": 0, "data": None, "error": f"{type(exception).__name__}: {exception}"}
    return wrapper

# ---------------------------
# VLAN token parsing
# ---------------------------

def _parse_vlan_token(token: str) -> Dict[str, Any]:
    """Return {'kind': 'special'|'single'|'range'|'invalid', 'value': ...}."""
    normalized_vlan_token = str(token).strip().lower()
    if normalized_vlan_token in {"any", "untagged"}:
        return {"kind": "special", "value": normalized_vlan_token}
    if ":" in normalized_vlan_token:
        try:
            start_value, end_value = map(int, normalized_vlan_token.split(":"))
            return {"kind": "range", "value": (start_value, end_value)}
        except Exception:  # noqa: BLE001
            return {"kind": "invalid", "value": normalized_vlan_token}
    if normalized_vlan_token.isdigit():
        return {"kind": "single", "value": int(normalized_vlan_token)}
    return {"kind": "invalid", "value": normalized_vlan_token}


def _token_fully_contained(token: str, available: List[str]) -> bool:
    """
    Check if requested VLAN token is within available ranges/tokens.
    available is like ["2990-2999", "4015-4094"] or ["2990", "3001-3003"].
    Special tokens ('any','untagged'): require explicit presence.
    """
    parsed_token = _parse_vlan_token(token)
    if parsed_token["kind"] == "invalid":
        return False

    available_ranges: List[tuple[int, int]] = []
    special_tokens_advertised = set()

    for advertised_item in available or []:
        available_token_text = str(advertised_item).strip().lower()

        if available_token_text in {"any", "untagged"}:
            special_tokens_advertised.add(available_token_text)
            continue

        if ":" in available_token_text or "-" in available_token_text:
            range_separator = ":" if ":" in available_token_text else "-"
            try:
                range_start_vlan, range_end_vlan = map(int, available_token_text.split(range_separator))
                if range_start_vlan <= range_end_vlan:
                    available_ranges.append((range_start_vlan, range_end_vlan))
            except Exception:  # noqa: BLE001
                continue
        elif available_token_text.isdigit():
            single_vlan_number = int(available_token_text)
            available_ranges.append((single_vlan_number, single_vlan_number))

    if parsed_token["kind"] == "special":
        return parsed_token["value"] in special_tokens_advertised

    if parsed_token["kind"] == "single":
        single_requested_vlan = parsed_token["value"]
        return any(
            range_start_vlan <= single_requested_vlan <= range_end_vlan
            for (range_start_vlan, range_end_vlan) in available_ranges
        )

    if parsed_token["kind"] == "range":
        requested_start_vlan, requested_end_vlan = parsed_token["value"]
        if requested_start_vlan > requested_end_vlan:
            return False

        current_vlan = requested_start_vlan
        for available_start_vlan, available_end_vlan in sorted(available_ranges):
            if available_end_vlan < current_vlan:
                continue
            if available_start_vlan > current_vlan:
                # gap not covered
                return False
            current_vlan = available_end_vlan + 1
            if current_vlan > requested_end_vlan:
                break
        return current_vlan > requested_end_vlan

    return False


# ---------------------------
# SDXClient
# ---------------------------

class SDXClient:
    """Thin HTTP client for SDX routes with guided endpoint selection."""

    def __init__(
        self,
        timeout: float = 6.0,
        *,
        token: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not BASE_URL:
            raise ValueError("BASE_URL is required")
        self.base_url = BASE_URL.rstrip("/")
        self.timeout = timeout

        # Reuse provided session or create one
        self.session = session or requests.Session()
        self.session.headers.setdefault("Content-Type", "application/json")

        # Authorization: prefer explicitly provided token; else try Fablib; else record error
        self.auth_error: Optional[str] = None
        bearer_token = token
        if bearer_token is None:
            token_result = _load_fabric_token()
            if token_result["status_code"] == 200 and token_result["data"]:
                bearer_token = token_result["data"]
            else:
                self.auth_error = token_result["error"] or "unable to load FABRIC token"

        if bearer_token:
            self.session.headers["Authorization"] = f"Bearer {bearer_token}"

        # L2VPN payload metadata (staged once)
        self._l2vpn_name: Optional[str] = None
        self._l2vpn_ownership: Optional[str] = None
        self._l2vpn_notifications: Optional[List[Dict[str, str]]] = None
        self._l2vpn_service_id: Optional[str] = None
        # Selection state
        self._first_endpoint: Optional[Dict[str, Any]] = None
        self._second_endpoint: Optional[Dict[str, Any]] = None

    # ---------- Session helpers ----------
    @_api_guard
    def set_token(self, token: Optional[str] = None) -> Dict[str, Any]:
        error_message = _missing_params(token=token)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.auth_error = None
        return {"status_code": 200, "data": True, "error": None}

    @_api_guard
    def get_selection(self) -> Dict[str, Any]:
        return {
                "status_code": 200,
                "data": {
                    "name": self._l2vpn_name,
                    "notifications": self._l2vpn_notifications,
                    "first": self._first_endpoint,
                    "second": self._second_endpoint,
                    "service_id": self._l2vpn_service_id,
                    },
                "error": None,
                }

    @_api_guard
    def clear_selection(self) -> Dict[str, Any]:
        self._l2vpn_name = None
        self._l2vpn_ownership = None
        self._l2vpn_notifications = None
        self._l2vpn_service_id = None
        self._first_endpoint = None
        self._second_endpoint = None
        return self.get_selection()

    @_api_guard
    def get_selected_endpoints(self) -> Dict[str, Any]:
        return {
            "status_code": 200,
            "data": {"first": self._first_endpoint, "second": self._second_endpoint},
            "error": None,
        }

    # ---------- Listings (pass-through) ----------
    @_api_guard
    def get_topology(self) -> Dict[str, Any]:
        """Fetch raw topology via the API route using the client's Bearer token."""
        return _http_request(
            self.session,
            self.base_url,
            "GET",
            "/topology",
            accept="application/json",
            timeout=self.timeout,
            expect_json=True,
        )

    @_api_guard
    def get_available_ports(
        self,
        *,
        search: Optional[str] = None,
        filter: Optional[str] = None,
        limit: Optional[int] = None,
        fields: Optional[str] = None,
        format: str = "html",  # "html" (default) or "json"
    ) -> Dict[str, Any]:
        params: Dict[str, str] = {"format": format}
        if limit:
            params["limit"] = str(limit)
        if filter:
            params["filter"] = filter
        elif search:
            params["search"] = search
        if fields:
            params["fields"] = fields

        accept = "text/html" if format == "html" else "application/json"
        expect_json = format != "html"
        return _http_request(
            self.session, self.base_url, "GET", "/available_ports",
            params=params, accept=accept, timeout=self.timeout, expect_json=expect_json,
        )

    # ---------- VLAN availability (pass-throughs) ----------
    @_api_guard
    def get_all_vlans_available(self) -> Dict[str, Any]:
        """Bulk VLAN availability for all ports."""
        return _http_request(
            self.session, self.base_url, "GET", "/available_vlans",
            params={"format": "json"}, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    @_api_guard
    def get_port_vlans_available(self, port_id: Optional[str] = None) -> Dict[str, Any]:
        """VLAN availability for a single port."""
        error_message = _missing_params(port_id=port_id)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}
        params: Dict[str, str] = {"format": "json", "port_id": str(port_id)}
        return _http_request(
            self.session, self.base_url, "GET", "/available_vlans",
            params=params, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    # ---------- Internal VLAN availability helper ----------
    def _check_vlan_available_on_port(self, port_id: str, vlan_token: str) -> Dict[str, Any]:
        """Call /available_vlans for port_id and check vlan_token containment."""
        availability_response = self.get_port_vlans_available(port_id)
        if availability_response["status_code"] != 200:
            return {
                "status_code": 0,
                "data": None,
                "error": availability_response.get("error") or "unable to check VLAN availability",
            }

        parsed_payload = availability_response.get("data", {})
        available_tokens: List[str] = []
        if isinstance(parsed_payload, dict):
            vlans_records = parsed_payload.get("vlans") or []
            if vlans_records and isinstance(vlans_records, list) and isinstance(vlans_records[0], dict):
                available_tokens = vlans_records[0].get("vlans_available") or []

        is_token_contained = _token_fully_contained(vlan_token, available_tokens)
        if not is_token_contained:
            return {
                "status_code": 0,
                "data": {"port_id": port_id, "available": available_tokens},
                "error": f"VLAN '{vlan_token}' not available on port '{port_id}'",
            }
        return {"status_code": 200, "data": True, "error": None}

    # ---------- Endpoint setter ----------
    @_api_guard
    def set_endpoint(
        self,
        *,
        endpoint_position: Optional[str] = None,  # friendly missing-arg handling
        filter: Optional[str] = None,
        search: Optional[str] = None,
        port_id: Optional[str] = None,
        vlan: Optional[Union[str, int]] = None,
        prefer_untagged: bool = False,
    ) -> Dict[str, Any]:
        """
        One-shot setter:
          - port_id path: fetch /device_info → VLAN → set
          - filter/search path: /available_ports JSON → find matches → device_info → VLAN → set

        Rules:
          - If both filter and search are provided, filter wins.
          - If multiple rows match the filter/search, return an ambiguity error.
          - Port URN is always taken from "id".
          - Validate VLAN availability against /available_vlans (inline).
        """
        error_message = _missing_params(endpoint_position=endpoint_position)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}

        normalized_position = (endpoint_position or "").strip().lower()
        if normalized_position not in ("first", "second"):
            return {"status_code": 0, "data": None, "error": 'endpoint_position must be "first" or "second"'}

        # ---------- Direct Port ID path ----------
        if port_id:
            device_info_result = _fetch_device_info_by_port_id(self, port_id=port_id)
            if device_info_result["status_code"] != 200:
                return device_info_result

            chosen_vlan_token = str(vlan) if vlan is not None else _choose_vlan_from_device_info(
                device_info_result["data"], prefer_untagged=prefer_untagged
            )
            if not chosen_vlan_token:
                return {"status_code": 0, "data": None, "error": "no usable VLAN found"}

            # Validate basic shape and availability
            try:
                _validate_endpoint_dict({"port_id": str(port_id), "vlan": str(chosen_vlan_token)})
            except Exception as validation_error:  # noqa: BLE001
                return {"status_code": 0, "data": None, "error": str(validation_error)}

            availability_check = self._check_vlan_available_on_port(str(port_id), str(chosen_vlan_token))
            if availability_check["status_code"] != 200:
                return availability_check

            endpoint_data = {"port_id": str(port_id), "vlan": str(chosen_vlan_token)}
            if normalized_position == "first":
                self._first_endpoint = endpoint_data
            else:
                self._second_endpoint = endpoint_data
            return {"status_code": 200, "data": endpoint_data, "error": None}

        # ---------- Filter / Search path ----------
        query_text = filter or search
        if not query_text:
            return {"status_code": 0, "data": None, "error": "either port_id or filter/search is required"}

        use_filter_flag = bool(filter)
        listing_result = _list_available_ports_json(self, query_text, use_filter=use_filter_flag)
        if listing_result["status_code"] != 200 or not isinstance(listing_result["data"], (dict, list)):
            return {"status_code": 0, "data": None, "error": listing_result.get("error") or "unable to list endpoints"}

        rows = _extract_rows_list(listing_result["data"])
        matches = _find_matching_rows(rows, query_text)

        if not matches:
            return {"status_code": 0, "data": None, "error": f"no matching {normalized_position} endpoint"}

        if len(matches) > 1:
            candidate_ids = [str(row.get("id") or "") for row in matches[:8]]
            return {
                "status_code": 0,
                "data": {"candidates": candidate_ids},
                "error": f"ambiguous filter/search matched {len(matches)} ports; refine or use exact port_id",
            }

        chosen_row = matches[0]
        chosen_port_id = str(chosen_row.get("id") or "").strip()
        if not chosen_port_id:
            return {"status_code": 0, "data": None, "error": "row missing Port URN in 'id'"}

        device_info_result = _fetch_device_info_by_port_id(self, port_id=chosen_port_id)
        if device_info_result["status_code"] != 200:
            return device_info_result

        chosen_vlan_token = str(vlan) if vlan is not None else _choose_vlan_from_device_info(
            device_info_result["data"], prefer_untagged=prefer_untagged
        )
        if not chosen_vlan_token:
            return {"status_code": 0, "data": None, "error": "no usable VLAN found"}

        # Validate shape + availability
        try:
            _validate_endpoint_dict({"port_id": chosen_port_id, "vlan": str(chosen_vlan_token)})
        except Exception as validation_error:  # noqa: BLE001
            return {"status_code": 0, "data": None, "error": str(validation_error)}

        availability_check = self._check_vlan_available_on_port(chosen_port_id, str(chosen_vlan_token))
        if availability_check["status_code"] != 200:
            return availability_check

        endpoint_data = {"port_id": chosen_port_id, "vlan": str(chosen_vlan_token)}
        if normalized_position == "first":
            self._first_endpoint = endpoint_data
        else:
            self._second_endpoint = endpoint_data

        return {"status_code": 200, "data": endpoint_data, "error": None}

    # ---------- L2VPN metadata (stage once) ----------
    @_api_guard
    def set_l2vpn_payload(
        self,
        *,
        name: str,
        notifications: Optional[Union[str, List[str], Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Stage L2VPN metadata (name + notifications). Validates and stores internally.
        """
        error_message = _missing_params(name=name)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}

        # Normalize + validate
        try:
            _validate_name(name)  # type: ignore[arg-type]
            self._l2vpn_name = name
            
            if notifications is not None:
                validated = _validate_notifications(notifications)
                if not validated:  # invalid, empty, or >10 entries
                    return {
                        "status_code": 0,
                        "data": None,
                        "error": "invalid notifications (must be 1–10 valid email addresses)",
                    }
                self._l2vpn_notifications = validated
            else:
                self._l2vpn_notifications = []
        except Exception as validation_error:  # noqa: BLE001
            return {"status_code": 0, "data": None, "error": str(validation_error)}
        
        if not self._l2vpn_name:
            return {"status_code": 0, "data": None, "error": "missing L2VPN name (set via set_l2vpn_payload)"}
        if not self._first_endpoint or not self._second_endpoint:
            return {"status_code": 0, "data": None, "error": "missing selection: first and/or second endpoint"}

        endpoints = [
            {"port_id": self._first_endpoint["port_id"], "vlan": self._first_endpoint["vlan"]},
            {"port_id": self._second_endpoint["port_id"], "vlan": self._second_endpoint["vlan"]},
        ]
        payload = {
                "name": self._l2vpn_name,
                "endpoints": endpoints,
                }
        if self._l2vpn_notifications:
            payload["notifications"] = self._l2vpn_notifications

        return {"status_code": 200, "data": payload, "error": None}

    # ---------- Preview (re-check availability then return payload) ----------
    @_api_guard
    def get_l2vpn_payload(self) -> Dict[str, Any]:
        """
        Build and return the L2VPN payload from staged metadata and endpoints.
        Pure local validation (no network availability checks here).
        """
        if not self._l2vpn_name:
            return {"status_code": 0, "data": None, "error": "missing L2VPN name (set via set_l2vpn_payload)"}
        if not self._first_endpoint or not self._second_endpoint:
            return {"status_code": 0, "data": None, "error": "missing selection: first and/or second endpoint"}

        endpoints = [
            {"port_id": self._first_endpoint["port_id"], "vlan": self._first_endpoint["vlan"]},
            {"port_id": self._second_endpoint["port_id"], "vlan": self._second_endpoint["vlan"]},
        ]

        # Local policy validation (shape + same-VLAN rules)
        try:
            _validate_endpoints(endpoints)
        except Exception as validation_error:  # noqa: BLE001
            return {"status_code": 0, "data": None, "error": str(validation_error)}

        payload = {
                "name": self._l2vpn_name,
                "endpoints": endpoints,
                }
        if self._l2vpn_notifications:
            payload["notifications"] = self._l2vpn_notifications

        return {"status_code": 200, "data": payload, "error": None}

    @_api_guard
    def create_l2vpn_from_selection(self) -> Dict[str, Any]:
        """
        POST /l2vpn with the previewed payload (ensures availability checks first).
        """
        result = self.get_l2vpn_payload()
        if result["status_code"] != 200:
            return result
        response = _http_request(
            self.session, self.base_url, "POST", "/l2vpn",
            json_body=result["data"], accept="application/json",
            timeout=self.timeout, expect_json=True,
        )
        if response["status_code"] in (200, 201) and isinstance(response.get("data"), dict):
            self._l2vpn_service_id = response["data"].get("service_id")
        return response

    # ---------- Raw JSON mirrors ----------
    @_api_guard
    def get_l2vpns(self, **query: Any) -> Dict[str, Any]:
        query.setdefault("format", "json")
        return _http_request(
            self.session, self.base_url, "GET", "/l2vpns",
            params=query, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    @_api_guard
    def get_l2vpn(self, service_id: Optional[str] = None) -> Dict[str, Any]:
        if not service_id:
            service_id = self._l2vpn_service_id or None
        error_message = _missing_params(service_id=service_id)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}
        return _http_request(
            self.session, self.base_url, "GET", f"/l2vpn/{service_id}",
            accept="application/json", timeout=self.timeout, expect_json=True,
        )

    @_api_guard
    def update_l2vpn(self, service_id: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
        if not service_id:
            service_id = self._l2vpn_service_id or None
        error_message = _missing_params(service_id=service_id)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}
        return _http_request(
            self.session, self.base_url, "PATCH", f"/l2vpn/{service_id}",
            json_body=fields or None, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    @_api_guard
    def delete_l2vpn(self, service_id: Optional[str] = None) -> Dict[str, Any]:
        if not service_id:
            service_id = self._l2vpn_service_id or None
        error_message = _missing_params(service_id=service_id)
        if error_message:
            return {"status_code": 0, "data": None, "error": error_message}
        return _http_request(
            self.session, self.base_url, "DELETE", f"/l2vpn/{service_id}",
            accept="application/json", timeout=self.timeout, expect_json=True,
        )

