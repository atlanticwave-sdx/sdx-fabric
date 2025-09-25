# SDXClient

A thin Python client that wraps the SDX HTTP routes, loads the FABRIC token automatically, and guides you through creating an **L2VPN** by selecting endpoints.  

It mirrors the existing API (available ports, device info, L2VPN CRUD), keeps response formats consistent, and maintains only the minimal state needed to assemble the final L2VPN payload.

---

## Key Points

- Uses **FABRIC authentication** (token loaded via fablib; no token argument needed).  
- Provides a guided flow: **set first endpoint → set second endpoint → preview → create**.  
- One unified method:  
  - `set_endpoint(endpoint_position="first", ...)`  
  - `set_endpoint(endpoint_position="second", ...)`  
- VLAN choice is derived from `/device_info`; supports preferring **untagged**.  
- Consistent return shape across all methods:  

```python
{
  "status_code": int,
  "data": Any,
  "error": Optional[str]
}
```

---

## Requirements

- Python **3.9 – 3.12**  
- `requests`  
- `fabrictestbed-extensions` (for automatic FABRIC token loading)  
- A valid **FABRIC token** (fablib locates it automatically)  

---

## Guided Flow (Step by Step)

### 1. Explore available ports
```python
client.get_available_ports(search="FABRIC", limit=20)
```

---

### 2. Begin a new selection
```python
client.begin_l2vpn_selection()
```

---

### 3. Set the first endpoint
By filter:
```python
client.set_endpoint(endpoint_position="first", min_filter="SW17:7")
```

By exact Port ID:
```python
client.set_endpoint(endpoint_position="first", port_id="urn:sdx:port:amlight.net:MIA-MI1-SW17:7")
```

---

### 4. Set the second endpoint
By filter (with VLAN preference):
```python
client.set_endpoint(endpoint_position="second", min_filter="SW17:27", prefer_untagged=True)
```

By exact Port ID:
```python
client.set_endpoint(endpoint_position="second", port_id="urn:sdx:port:amlight.net:MIA-MI1-SW17:27", prefer_untagged=True)
```

---

### 5. Preview the payload
```python
client.preview_l2vpn_payload(name="test-sdxlib-mia", notifications="lmarinve@fiu.edu")
```

---

### 6. Create the L2VPN
```python
client.create_l2vpn_from_selection(name="test-sdxlib-mia", notifications="lmarinve@fiu.edu")
```

