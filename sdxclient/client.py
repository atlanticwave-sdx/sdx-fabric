"""Stateful thin client (user-facing) with correct HTML/JSON handling."""
from typing import Any, Dict, Optional
import requests

from .config import BASE_URL
from .fablib_token import _load_fabric_token
from .http import _http_request
from .selection_utils import (
    _begin_selection_state,
    _build_l2vpn_payload,
)


class SDXClient:
    """Thin HTTP client for SDX routes with guided first/second endpoint storage."""

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
        bearer = token
        if bearer is None:
            token_result = _load_fabric_token()
            if token_result["status_code"] == 200 and token_result["data"]:
                bearer = token_result["data"]
            else:
                self.auth_error = token_result["error"] or "unable to load FABRIC token"

        if bearer:
            self.session.headers["Authorization"] = f"Bearer {bearer}"

        # Simple selection state (set explicitly by the user)
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

    # ---------- Listings: HTML by default, JSON on request ----------
    def get_available_ports(
        self,
        *,
        search: Optional[str] = None,
        limit: int = 20,
        fields: Optional[str] = None,
        format: str = "html",  # "html" (default) or "json"
    ) -> Dict[str, Any]:
        params: Dict[str, str] = {"format": format, "limit": str(limit)}
        if search:
            params["search"] = search
        if fields:
            params["fields"] = fields
        accept = "text/html" if format == "html" else "application/json"
        expect_json = (format != "html")
        return _http_request(
            self.session, self.base_url, "GET", "/available_ports",
            params=params, accept=accept, timeout=self.timeout, expect_json=expect_json,
        )

    def get_first_endpoints(
        self,
        *,
        search: Optional[str] = None,
        limit: int = 20,
        fields: Optional[str] = None,
        format: str = "html",  # "html" (default) or "json"
    ) -> Dict[str, Any]:
        params: Dict[str, str] = {"format": format, "limit": str(limit)}
        if search:
            params["search"] = search
        if fields:
            params["fields"] = fields
        accept = "text/html" if format == "html" else "application/json"
        expect_json = (format != "html")
        return _http_request(
            self.session, self.base_url, "GET", "/available_ports",
            params=params, accept=accept, timeout=self.timeout, expect_json=expect_json,
        )

    def get_second_endpoints(
        self,
        *,
        search: Optional[str] = None,
        limit: int = 20,
        fields: Optional[str] = None,
        format: str = "html",  # "html" (default) or "json"
    ) -> Dict[str, Any]:
        params: Dict[str, str] = {"format": format, "limit": str(limit)}
        if search:
            params["search"] = search
        if fields:
            params["fields"] = fields
        accept = "text/html" if format == "html" else "application/json"
        expect_json = (format != "html")
        return _http_request(
            self.session, self.base_url, "GET", "/available_ports",
            params=params, accept=accept, timeout=self.timeout, expect_json=expect_json,
        )

    # ---------- Explicit setters (you provide port_id and vlan) ----------
    def set_first_endpoint_by_port_id(self, *, port_id: str, vlan: str = "any") -> Dict[str, Any]:
        if not port_id:
            return {"status_code": 0, "data": None, "error": "port_id is required"}
        self._first_endpoint = {"port_id": str(port_id), "vlan": str(vlan)}
        return {"status_code": 200, "data": self._first_endpoint, "error": None}

    def set_second_endpoint_by_port_id(self, *, port_id: str, vlan: str = "any") -> Dict[str, Any]:
        if not port_id:
            return {"status_code": 0, "data": None, "error": "port_id is required"}
        self._second_endpoint = {"port_id": str(port_id), "vlan": str(vlan)}
        return {"status_code": 200, "data": self._second_endpoint, "error": None}

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

