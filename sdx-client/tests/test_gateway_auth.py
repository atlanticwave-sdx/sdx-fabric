import os

import pytest
import requests

BASE_URL = os.getenv("SDX_BASE_URL", "https://sdxapi.atlanticwave-sdx.net").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("SDX_TEST_TIMEOUT", "8"))
VERIFY_TLS = os.getenv("SDX_TLS_VERIFY", "true").lower() in {"1", "true", "yes", "on"}


def _request_root(auth_header_value: str | None) -> requests.Response:
    headers = {"Accept": "application/json"}
    if auth_header_value is not None:
        headers["Authorization"] = auth_header_value
    return requests.get(f"{BASE_URL}/", headers=headers, timeout=TIMEOUT_SECONDS, verify=VERIFY_TLS)


def _assert_json_error(response: requests.Response, expected_status: int, expected_error: str | None = None) -> None:
    assert response.status_code == expected_status
    payload = response.json()
    assert isinstance(payload, dict)
    assert "error" in payload
    assert "message" in payload
    if expected_error is not None:
        assert payload["error"] == expected_error


def test_gateway_up_no_token_returns_missing_token() -> None:
    response = _request_root(auth_header_value=None)
    _assert_json_error(response, expected_status=401, expected_error="missing_token")


@pytest.mark.parametrize(
    "auth_value,expected_error",
    [
        ("Bearer", "invalid_authorization"),
        ("Bearer ", "invalid_authorization"),
        ("Basic abc", "invalid_authorization"),
        ("junk", "invalid_authorization"),
    ],
)
def test_gateway_malformed_authorization_header(auth_value: str, expected_error: str) -> None:
    response = _request_root(auth_header_value=auth_value)
    _assert_json_error(response, expected_status=401, expected_error=expected_error)


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        "abc.def",  # malformed segments
        "abc.def.ghi",  # looks like jwt but not base64 json
    ],
)
def test_gateway_garbage_token_rejected(token: str) -> None:
    response = _request_root(auth_header_value=f"Bearer {token}")
    assert response.status_code == 401
    payload = response.json()
    assert isinstance(payload, dict)
    # Depending on where it fails (decode vs verify), error can differ.
    assert payload.get("error") in {"invalid_token", "token_rejected", "invalid_jwt"}


def test_gateway_expired_token_rejected_if_provided() -> None:
    expired_jwt = os.getenv("SDX_EXPIRED_JWT")
    if not expired_jwt:
        pytest.skip("SDX_EXPIRED_JWT not set")

    response = _request_root(auth_header_value=f"Bearer {expired_jwt}")
    assert response.status_code == 401
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("error") in {"token_rejected", "invalid_token"}


def test_gateway_valid_token_allows_request_if_provided() -> None:
    valid_jwt = os.getenv("SDX_VALID_JWT")
    if not valid_jwt:
        pytest.skip("SDX_VALID_JWT not set")

    response = _request_root(auth_header_value=f"Bearer {valid_jwt}")

    # We only assert "auth passed" by asserting we did NOT get the auth.lua 401.
    # Upstream could still return 200/404/405/etc depending on / route behavior.
    assert response.status_code != 401
