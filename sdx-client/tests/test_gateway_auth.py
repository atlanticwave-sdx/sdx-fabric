from pathlib import Path
import pytest
import requests
import os

BASE_URL = os.getenv("SDX_BASE_URL", "https://sdxapi.atlanticwave-sdx.net").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("SDX_TEST_TIMEOUT", "8"))
VERIFY_TLS = os.getenv("SDX_TLS_VERIFY", "true").lower() in {"1", "true", "yes", "on"}

TOKENS_DIR = Path(__file__).resolve().parent / "tokens"


def _read_token_file(token_path: Path) -> str:
    lines: list[str] = []
    for raw_line in token_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)

    token = "".join(lines).strip()
    if not token:
        pytest.skip(f"token file empty: {token_path.name}")

    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    return token


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


def _iter_token_files() -> list[Path]:
    if not TOKENS_DIR.exists():
        pytest.skip(f"tokens dir missing: {TOKENS_DIR}")

    token_files = sorted([p for p in TOKENS_DIR.iterdir() if p.is_file() and p.name != "README.md"])
    if not token_files:
        pytest.skip(f"no token files found in {TOKENS_DIR}")

    return token_files


@pytest.mark.parametrize("token_path", _iter_token_files(), ids=lambda p: p.name)
def test_gateway_token_files_roundtrip(token_path: Path) -> None:
    token = _read_token_file(token_path)
    response = _request_root(auth_header_value=f"Bearer {token}")

    # Convention by filename (simple + not complicated):
    name = token_path.name.lower()
    is_expected_valid = "valid" in name
    is_expected_expired = "expired" in name
    is_expected_malformed = "malformed" in name

    if is_expected_valid:
        # Valid token should pass auth.lua (upstream can still return 200/404/etc)
        assert response.status_code != 401
        return

    # For expired/malformed/anything-else: must be rejected by auth.lua
    assert response.status_code == 401
    payload = response.json()
    assert isinstance(payload, dict)

    if is_expected_expired:
        assert payload.get("error") in {"token_rejected", "invalid_token"}
    elif is_expected_malformed:
        assert payload.get("error") in {"invalid_token", "token_rejected", "invalid_jwt"}
    else:
        # default: still must be some auth-related error
        assert payload.get("error") in {"invalid_token", "token_rejected", "missing_token", "invalid_authorization", "invalid_jwt"}
