"""FABRIC token retrieval (private)."""
from typing import Any, Dict
import json

try:
    from fabrictestbed_extensions.fablib.fablib import FablibManager  # type: ignore
except Exception:  # pragma: no cover
    FablibManager = None  # type: ignore


def _load_fabric_token() -> Dict[str, Any]:
    if FablibManager is None:
        return {"status_code": 0, "data": None, "error": "FablibManager not available in this environment"}
    try:
        fablib = FablibManager()
        token_path = fablib.get_token_location()
        with open(token_path, "r", encoding="utf-8") as handle:
            token_json = json.load(handle)
        id_token = token_json.get("id_token")
        if not id_token:
            return {"status_code": 0, "data": None, "error": "id_token missing in FABRIC token file"}
        return {"status_code": 200, "data": id_token, "error": None}
    except Exception as exc:  # pragma: no cover
        return {"status_code": 0, "data": None, "error": f"fablib token load failed: {exc}"}

