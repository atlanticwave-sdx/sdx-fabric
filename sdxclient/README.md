# SDXClient

A thin Python client that wraps your SDX HTTP routes, loads the FABRIC token automatically, and guides you through creating an **L2VPN** by selecting a **first endpoint** and a **second endpoint**.  

It mirrors your existing API (available ports, device info, L2VPN CRUD), keeps the response formats you already return (HTML or JSON), and maintains only the minimal state needed to assemble the final L2VPN payload.

---

## Key Points

- Uses **FABRIC authentication** (token loaded via fablib; no token argument needed).  
- Mirrors server routes; no frontend code or extra transformations.  
- Provides a guided flow: **get endpoints → set endpoints → preview → create**.  
- Two ways to select endpoints:  
  - By simple text filtering over listed rows (e.g., device and port).  
  - By exact **Port ID** only (e.g., `urn:sdx:port:amlight.net:MIA-MI1-SW17:7`).  
- VLAN choice is always derived from `/device_info`; supports preferring **untagged**.  
- Consistent return shape across all methods: `status_code`, `data`, `error`.  
- **First/second** naming is multipoint-ready for future third/fourth endpoints.  

---

## Requirements

- Python **3.9 – 3.12**  
- `requests` and `fabrictestbed-extensions` installed  
- Access to a valid **FABRIC token** on the machine (fablib will locate it)  

---

## Guided Flow (Step by Step with Methods)

1. **EXPLORE AVAILABLE PORTS (FILTER BY ENTITY)**  
   - Method: `client.get_available_ports(search="FABRIC", limit=20)`  
   - Lists ports restricted to FABRIC.  

2. **BEGIN A NEW SELECTION**  
   - Method: `client.begin_l2vpn_selection()`  
   - Clears any previously stored endpoints.  

3. **GET FIRST ENDPOINTS**  
   - Method: `client.get_first_endpoints(search="MIA", limit=20)`  
   - Returns HTML viewable table; JSON cached internally.  

4. **SET THE FIRST ENDPOINT**  
   - Method (by filter): `client.set_first_endpoint(min_filter="SW17:7")`  
   - Method (by Port ID):  
     `client.set_first_endpoint_by_port_id("urn:sdx:port:amlight.net:MIA-MI1-SW17:7")`  

5. **GET SECOND ENDPOINTS**  
   - Method: `client.get_second_endpoints(search="MIA", limit=20)`  
   - Includes VLANs in Use.  

6. **SET THE SECOND ENDPOINT**  
   - Method (by filter): `client.set_second_endpoint(min_filter="SW17:27", prefer_untagged=True)`  
   - Method (by Port ID):  
     `client.set_second_endpoint_by_port_id("urn:sdx:port:amlight.net:MIA-MI1-SW17:27", prefer_untagged=True)`  

7. **PREVIEW THE PAYLOAD**  
   - Method:  
     `client.preview_l2vpn_payload(name="test-sdxlib-mia", notifications="lmarinve@fiu.edu")`  
   - Shows the exact JSON body before creation.  

8. **CREATE THE L2VPN**  
   - Method:  
     `client.create_l2vpn_from_selection(name="test-sdxlib-mia", notifications="lmarinve@fiu.edu")`  
   - Submits to the controller and returns the server’s response.  

---

## Example Flow (Concrete)

- **Step 1 – Available Ports**  
  → `client.get_available_ports(search="FABRIC", limit=20)`

- **Step 2 – New Selection**  
  → `client.begin_l2vpn_selection()`

- **Step 3 – First Endpoints (MIA)**  
  → `client.get_first_endpoints(search="MIA", limit=20)`

- **Step 4 – Set First Endpoint**  
  → `client.set_first_endpoint_by_port_id("urn:sdx:port:amlight.net:MIA-MI1-SW17:7")`

- **Step 5 – Second Endpoints (MIA)**  
  → `client.get_second_endpoints(search="MIA", limit=20)`

- **Step 6 – Set Second Endpoint**  
  → `client.set_second_endpoint_by_port_id("urn:sdx:port:amlight.net:MIA-MI1-SW17:27", prefer_untagged=True)`

- **Step 7 – Preview Payload**  
  → `client.preview_l2vpn_payload(name="test-sdxlib-mia", notifications="lmarinve@fiu.edu")`

- **Step 8 – Create L2VPN**  
  → `client.create_l2vpn_from_selection(name="test-sdxlib-mia", notifications="lmarinve@fiu.edu")`

---

## Notes

- Token is loaded via fablib automatically.  
- VLANs are only chosen from `/device_info`.  
- First/second naming can be extended for multipoint in the future.  

