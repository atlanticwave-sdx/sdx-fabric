# SDXClient

A thin Python client that wraps the SDX HTTP routes, stages L2VPN payload metadata, guides endpoint selection, and keeps responses consistent.

- Returns dict everywhere: {"status_code": int, "data": Any, "error": Optional[str]}
- No user-facing tracebacks; friendly errors only.

---

## Key Points

- Uses **FABRIC authentication** (token loaded via fablib; no token argument needed).  
- Provides a guided flow: **set first endpoint → set second endpoint → preview → create**.  
- One unified method:  
  - `set_endpoint(endpoint_position="first", ...)`  
  - `set_endpoint(endpoint_position="second", ...)`  
- VLAN choice is derived from `/device_info`; supports preferring **untagged**.  
- Consistent return shape across all methods:  

## Initialization

```python
from sdxclient import SDXClient
client = SDXClient(timeout=6.0)            # tries FABRIC token
```

## Return Shape (always)

```python
{
  "status_code": int,
  "data": Any,
  "error": Optional[str]
}
```

- status_code == 0 → client-side validation / network failure
- status_code >= 400 → server-side error (with best-effort error message)
---

## Requirements

- Python **3.9 – 3.12**  
- `requests`  
- `fabrictestbed-extensions` (for automatic FABRIC token loading)  
- A valid **FABRIC token** (fablib locates it automatically)  

---

## Core Read APIs (pass-through)

```python
client.get_topology()
client.get_available_ports(search=None, filter=None, limit=None, fields=None, format="html|json")
client.get_all_vlans_available()
client.get_port_vlans_available(port_id)
```

**Notes:**
- filter wins over search.
- format="html" returns HTML table (string). format="json" returns structured JSON.

## Selection Flow (endpoints)

```python
client.clear_selection()
client.set_endpoint(
    endpoint_position="first" | "second",
    filter=None, search=None,
    port_id=None, vlan=None,
    prefer_untagged=False
)
client.get_selected_endpoints()
```

**Rules:**
- Use port_id for precise selection, or filter/search to resolve a single row.
- If multiple candidates match, you get an ambiguity error with a short candidate list.
- VLAN availability is checked inline against /available_vlans.

## L2VPN Payload: Stage → Preview → Create

**1) Stage payload metadata once**

```python
client.set_l2vpn_payload(
    name="project-alpha-l2vpn",
    notifications=["ops@example.org", "noc@example.org"]
)
```

- Validates name (non-empty, ≤ 50 chars).
- Validates notifications (1–10 emails; str input is normalized to a list).

**2) Build payload** locally (no network)
```python
payload_result = client.get_l2vpn_payload()
# -> {"name": "...", "notifications": [...], "endpoints": [{...}, {...}]}
```

- Requires both endpoints to be selected and metadata to be staged.
- Re-validates endpoint shape and rejects same-VLAN per policy (see “VLAN Rules”).
- No availability calls here.

**3) Preview payload with availability checks**
```python
preview_result = client.preview_l2vpn_payload()
# Re-checks VLAN availability via /available_vlans for both endpoints.
```

**4) Create L2VPN (uses previewed payload)**
```python
create_result = client.create_l2vpn_from_selection()
```

- Uses the staged name/notifications + selected endpoints.
- Performs preview internally first (includes availability checks).
- No need to pass name/notifications again here.

**CRUD Mirrors**
- client.get_l2vpns(**query)
- client.get_l2vpn(service_id)
- client.update_l2vpn(service_id, **fields)
- client.delete_l2vpn(service_id)

## Minimal End-to-End Example
```python
from sdxclient import SDXClient
client = SDXClient()
```

**1) Start fresh**
```python
client.clear_selection()
```

**2) Choose endpoints**
```python
client.set_endpoint(endpoint_position="first",  filter="SW17:7")
client.set_endpoint(endpoint_position="second", filter="SW17:27", prefer_untagged=True)
```

**3) Stage metadata once**
```python
client.set_l2vpn_payload(
    name="proj-alpha-mia-test",
    notifications="noc@example.org"
)
```

**4) Optional: local payload** (no network)
```python
local_payload = client.get_l2vpn_payload()
```

**5) Preview with availability checks**
```python
preview = client.preview_l2vpn_payload()
```

**6) Create**
```python
created = client.create_l2vpn_from_selection()
```

## Error Examples (friendly)
```python
client.get_port_vlans_available(None)
# {'status_code': 0, 'data': None, 'error': 'missing required parameter(s): port_id'}

client.set_endpoint(endpoint_position="first", filter="too-broad")
# {'status_code': 0, 'data': {'candidates': [...]}, 'error': 'ambiguous filter/search matched ...'}

client.get_l2vpn_payload()   # without staging metadata
# {'status_code': 0, 'data': None, 'error': 'missing L2VPN name (set via set_l2vpn_payload)'}
```

## VLAN Validation Rules for L2VPN

**Allowed forms**
- Numeric VLANs: 1..4095
- Ranges: A:B where 1 ≤ A < B ≤ 4095
- Keywords: any, untagged
- **(all is not allowed)**

## Mixing rules

- Numeric ↔ Range (e.g., 200 with 100:300)
- any ↔ untagged
- any/untagged mixed with numeric/range

## Rejection rules
- all mixed with anything (since all is not allowed at all)
- Same numeric VLAN twice (e.g., 200 & 200)
- Same exact range twice (e.g., 100:200 & 100:200)

## Tips

- Prefer format="json" for machine workflows; parse ports from /available_ports.
- If you pass both filter and search, filter is used.
- “No usable VLAN found” often means the port advertises none or they’re all in use.

- If you want to skip availability checks, use get_l2vpn_payload() and post it yourself; otherwise use create_l2vpn_from_selection() to keep checks on.

## Troubleshooting

- 401 / missing token → set a valid token or ensure FABRIC token is discoverable.
- Empty listings → loosen your filter/search; inspect /topology.
- Availability errors → verify get_port_vlans_available(port_id) shows a range that contains your requested VLAN token.

## Changelog (relevant)

- Added set_l2vpn_payload(name, notifications): stage metadata once.
- Added get_l2vpn_payload(): build local payload without network.
- create_l2vpn_from_selection() no longer requires passing name/notifications; it uses staged metadata and runs a preview internally.

# Install

## Production (PyPI)
pip install sdxclient
## or a specific version
pip install sdxclient==0.10.0

## Test (TestPyPI pre-releases)
- Prefer exact RC version when installing from TestPyPI

pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple \
            sdxclient==0.10.0rc1
- or allow any pre-release (if available)
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple \
            --pre sdxclient

## Runtime configuration (test vs prod API)

- sdxclient reads the base URL from the environment:

## Test (default if unset in config.py)
export SDX_BASE_URL=http://190.103.184.194

## Production
export SDX_BASE_URL=https://sdxapi.atlanticwave-sdx.ai

- If SDX_BASE_URL isn’t set, the package falls back to the default defined in sdxclient/config.py.

## Releasing (maintainers)

- This project uses GitHub Actions + Trusted Publishing.

## Branch/PR flow

- Open PRs as usual. CI will build only (no publish).

- On merge to main, if the version is a pre-release (contains rc), CI publishes to TestPyPI.

## Test release (TestPyPI)

- Bump version in sdx-client/pyproject.toml to an RC:

- version = "X.Y.ZrcN"


## Merge the PR to main or run the workflow manually:

- Actions → “Build & Publish (TestPyPI → PyPI)” → Run workflow

- target: testpypi

## Install for testing:

pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple \
            sdxclient==X.Y.ZrcN

## Production release (PyPI)

### Bump version to a final:

- version = "X.Y.Z"


### Tag and push the tag:

- git tag vX.Y.Z
- git push origin vX.Y.Z
- (Or run the workflow manually with target: pypi.)

## Install from PyPI:

pip install sdxclient==X.Y.Z

## Rules the workflow enforces

- TestPyPI requires version to contain rc.
- PyPI requires version without rc.
- Publishing uses OIDC (no API tokens).
- Manual run (optional)

## From GitHub → Actions → “Build & Publish (TestPyPI → PyPI)” → Run workflow:

- target: testpypi (expects rc in version)
- target: pypi (expects final version)
- Pick the branch that contains your version bump.
