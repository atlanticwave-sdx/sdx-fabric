"""Stateful thin client (user-facing) aligned with AW-SDX 2.0 Topology Data Model."""
from typing import Any, Dict, Optional
import requests

from .config import BASE_URL
from .fablib_token import _load_fabric_token
from .http import _http_request
from .selection_utils import (
    _begin_selection_state,
    _build_l2vpn_payload,
    _choose_vlan_from_device_info,
    _extract_rows_list,
    _find_matching_rows,           # <-- use new matcher
    _list_available_ports_json,
    _fetch_device_info_by_port_id,
)


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

        # Selection state
        self._first_endpoint: Optional[Dict[str, Any]] = None
        self._second_endpoint: Optional[Dict[str, Any]] = None

    def set_token(self, token: str) -> Dict[str, Any]:
        """Inject/replace the Bearer token at runtime."""
        if not token:
            return {"status_code": 0, "data": None, "error": "empty token"}
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.auth_error = None
        return {"status_code": 200, "data": True, "error": None}

    # ---------- Session helpers ----------
    def begin_l2vpn_selection(self) -> Dict[str, Any]:
        return _begin_selection_state(self)

    def clear_selection(self) -> Dict[str, Any]:
        return _begin_selection_state(self)

    def get_selected_endpoints(self) -> Dict[str, Any]:
        return {
            "status_code": 200,
            "data": {"first": self._first_endpoint, "second": self._second_endpoint},
            "error": None,
        }

    # ---------- Listings (pass-through) ----------
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

    # ---------- Unified endpoint setter ----------
    def set_endpoint(
        self,
        *,
        endpoint_position: str,         # "first" or "second"
        filter: Optional[str] = None,
        search: Optional[str] = None,
        port_id: Optional[str] = None,
        vlan: Optional[str] = None,
        prefer_untagged: bool = False,
    ) -> Dict[str, Any]:
        """
        One-shot setter:
          - port_id path: fetch device_info → VLAN → set
          - filter/search path: /available_ports JSON → find matches → device_info → VLAN → set

        Rules:
          - If both filter and search are provided, filter wins.
          - If multiple rows match the filter/search, return an ambiguity error.
          - Port URN is always taken from "id".
        """
        normalized_position = (endpoint_position or "").strip().lower()
        if normalized_position not in ("first", "second"):
            return {"status_code": 0, "data": None, "error": 'endpoint_position must be "first" or "second"'}

        # ---------- Direct Port ID path ----------
        if port_id:
            device_info_result = _fetch_device_info_by_port_id(self, port_id=port_id)
            if device_info_result["status_code"] != 200:
                return device_info_result

            chosen_vlan = vlan or _choose_vlan_from_device_info(
                device_info_result["data"], prefer_untagged=prefer_untagged
            )
            if not chosen_vlan:
                return {"status_code": 0, "data": None, "error": "no usable VLAN found"}

            endpoint_data = {"port_id": str(port_id), "vlan": str(chosen_vlan)}
            if normalized_position == "first":
                self._first_endpoint = endpoint_data
            else:
                self._second_endpoint = endpoint_data
            return {"status_code": 200, "data": endpoint_data, "error": None}

        # ---------- Filter / Search path ----------
        query_text = filter or search
        if not query_text:
            return {"status_code": 0, "data": None, "error": "either port_id or filter/search is required"}

        use_filter = bool(filter)
        listing_result = _list_available_ports_json(self, query_text, use_filter=use_filter)
        if listing_result["status_code"] != 200 or not isinstance(listing_result["data"], (dict, list)):
            return {"status_code": 0, "data": None, "error": listing_result.get("error") or "unable to list endpoints"}

        rows = _extract_rows_list(listing_result["data"])
        matches = _find_matching_rows(rows, query_text)

        if not matches:
            return {"status_code": 0, "data": None, "error": f"no matching {normalized_position} endpoint"}

        if len(matches) > 1:
            # Return a concise ambiguity message plus a short list of candidate URNs
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

        chosen_vlan = vlan or _choose_vlan_from_device_info(device_info_result["data"], prefer_untagged=prefer_untagged)
        if not chosen_vlan:
            return {"status_code": 0, "data": None, "error": "no usable VLAN found"}

        endpoint_data = {"port_id": chosen_port_id, "vlan": str(chosen_vlan)}
        if normalized_position == "first":
            self._first_endpoint = endpoint_data
        else:
            self._second_endpoint = endpoint_data

        return {"status_code": 200, "data": endpoint_data, "error": None}

    # ---------- Preview & create ----------
    def preview_l2vpn_payload(self, *, name: str, notifications: str) -> Dict[str, Any]:
        if not self._first_endpoint or not self._second_endpoint:
            return {"status_code": 0, "data": None, "error": "missing selection: first and/or second endpoint"}
        payload = _build_l2vpn_payload(
            name=name,
            notifications=notifications,
            first_endpoint=self._first_endpoint,
            second_endpoint=self._second_endpoint,
        )
        return {"status_code": 200, "data": payload, "error": None}

    def create_l2vpn_from_selection(self, *, name: str, notifications: str) -> Dict[str, Any]:
        preview = self.preview_l2vpn_payload(name=name, notifications=notifications)
        if preview["status_code"] != 200:
            return preview
        return _http_request(
            self.session, self.base_url, "POST", "/l2vpn",
            json_body=preview["data"], accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    # ---------- Raw JSON mirrors ----------
    def get_l2vpns(self, **query: Any) -> Dict[str, Any]:
        query.setdefault("format", "json")
        return _http_request(
            self.session, self.base_url, "GET", "/l2vpns",
            params=query, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    def get_l2vpn(self, service_id: str) -> Dict[str, Any]:
        return _http_request(
            self.session, self.base_url, "GET", f"/l2vpn/{service_id}",
            accept="application/json", timeout=self.timeout, expect_json=True,
        )

    def update_l2vpn(self, service_id: str, **fields: Any) -> Dict[str, Any]:
        return _http_request(
            self.session, self.base_url, "PATCH", f"/l2vpn/{service_id}",
            json_body=fields or None, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    def delete_l2vpn(self, service_id: str) -> Dict[str, Any]:
        return _http_request(
            self.session, self.base_url, "DELETE", f"/l2vpn/{service_id}",
            accept="application/json", timeout=self.timeout, expect_json=True,
        )

