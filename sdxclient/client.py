"""Stateful thin client (user-facing) that delegates private work to helpers."""
from typing import Any, Dict, List, Optional
import requests

from .fablib_token import _load_fabric_token
from .http import _http_request
from .selection_utils import (
    _begin_selection_state,
    _get_selected_endpoints,
    _get_first_endpoints_html,
    _get_second_endpoints_html,
    _set_first_endpoint,
    _set_second_endpoint,
    _set_first_endpoint_by_port_id,
    _set_second_endpoint_by_port_id,
    _build_l2vpn_payload,
)


class SDXClient:
    """Stateful, thin HTTP client for SDX routes with guided first/second endpoint selection."""

    def __init__(self, base_url: str, timeout: float = 6.0) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        token_result = _load_fabric_token()
        if token_result["status_code"] != 200:
            self.auth_error = token_result["error"] or "unable to load FABRIC token"
        else:
            self.auth_error = None
            fabric_token = token_result["data"]
            self.session.headers.update({"Authorization": f"Bearer {fabric_token}"})

        # Private state
        self._first_endpoint: Optional[Dict[str, Any]] = None
        self._second_endpoint: Optional[Dict[str, Any]] = None
        self._last_first_rows: Optional[List[Dict[str, Any]]] = None
        self._last_second_rows: Optional[List[Dict[str, Any]]] = None
        self._last_first_info: Optional[Dict[str, Any]] = None
        self._last_second_info: Optional[Dict[str, Any]] = None

    # ---------- User methods: session helpers ----------
    def begin_l2vpn_selection(self) -> Dict[str, Any]:
        return _begin_selection_state(self)

    def clear_selection(self) -> Dict[str, Any]:
        return _begin_selection_state(self)

    def get_selected_endpoints(self) -> Dict[str, Any]:
        return _get_selected_endpoints(self)

    # ---------- User methods: global available ports ----------
    def get_available_ports(self, **query: Any) -> Dict[str, Any]:
        """Pass-through to /available_ports (JSON). Use search='FABRIC', limit=20 to filter by entity."""
        return _http_request(
            self.session, self.base_url, "GET", "/available_ports",
            params=query or None, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

    # ---------- User methods: list endpoints ----------
    def get_first_endpoints(self, search: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Return HTML (string) and cache JSON rows for subsequent set_* calls."""
        return _get_first_endpoints_html(self, search, limit)

    def get_second_endpoints(self, search: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Return HTML (string) and cache JSON rows for subsequent set_* calls. Includes VLANs in Use."""
        return _get_second_endpoints_html(self, search, limit)

    # ---------- User methods: set endpoints by filter ----------
    def set_first_endpoint(self, min_filter: Optional[str] = None, prefer_untagged: Optional[bool] = None) -> Dict[str, Any]:
        return _set_first_endpoint(self, min_filter, prefer_untagged)

    def set_second_endpoint(self, min_filter: Optional[str] = None, prefer_untagged: Optional[bool] = None) -> Dict[str, Any]:
        return _set_second_endpoint(self, min_filter, prefer_untagged)

    # ---------- User methods: set endpoints by explicit Port ID ----------
    def set_first_endpoint_by_port_id(self, *, port_id: str, prefer_untagged: bool = False) -> Dict[str, Any]:
        return _set_first_endpoint_by_port_id(self, port_id, prefer_untagged)

    def set_second_endpoint_by_port_id(self, *, port_id: str, prefer_untagged: bool = False) -> Dict[str, Any]:
        return _set_second_endpoint_by_port_id(self, port_id, prefer_untagged)

    # ---------- User methods: preview & create ----------
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

    # ---------- User methods: raw mirrors ----------
    def get_l2vpns(self, **query: Any) -> Dict[str, Any]:
        return _http_request(
            self.session, self.base_url, "GET", "/l2vpns",
            params=query or None, accept="application/json",
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

    # ---------- Private method: now port_id-only ----------
    def _fetch_device_info_by_port_id(self, *, port_id: str) -> Dict[str, Any]:
        params = {"port_id": port_id, "format": "json"}
        return _http_request(
            self.session, self.base_url, "GET", "/device_info",
            params=params, accept="application/json",
            timeout=self.timeout, expect_json=True,
        )

