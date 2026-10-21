## AutoDrive TestBench API – QA Test Matrix  
*(focus on the endpoints shown in the contract – health check & vehicle catalogue)*  

| # | Endpoint | Method | Input (Query / Body) | Test Type | Test Description | Expected Result |
|---|----------|--------|----------------------|-----------|------------------|-----------------|
| **H‑001** | `/healthz` | GET | – | **Happy Path** | Call health‑check when the service is up and DB is reachable. | `200 OK` with JSON `{status:"UP", db:"CONNECTED", …}` |
| **H‑002** | `/healthz` | GET | – | **Happy Path** | Call health‑check after a graceful shutdown (service still responding). | `200 OK` with `"status":"SHUTTING_DOWN"` (or similar) – still a valid response. |
| **E‑001** | `/healthz` | GET | – | **Edge / Failure** | Simulate DB outage (e.g., stop DB container). | `503 Service Unavailable` with JSON indicating `db:"DISCONNECTED"` |
| **E‑002** | `/healthz` | GET | – | **Edge / Failure** | Service process crashes and is restarted by orchestrator. Verify the endpoint returns `200` after recovery. | `200 OK` after a short retry interval. |
| **B‑001** | `/vehicles` | GET | `status=ACTIVE` | **Boundary** | Request with a **valid** status filter that matches *all* vehicles. | `200 OK`, array length = total fleet size (verify pagination if present). |
| **B‑002** | `/vehicles` | GET | `status=UNKNOWN_STATUS` | **Boundary / Edge** | Use a status value that is not defined in the enum. | `400 Bad Request` with validation error message. |
| **B‑003** | `/vehicles` | GET | `status=` (empty) | **Boundary** | Omit the status filter (or pass empty string). | `200 OK` returning **all** vehicles regardless of status. |
| **H‑003** | `/vehicles` | GET | `status=MAINTENANCE` | **Happy Path** | Filter by a status that returns a **small** subset (e.g., 1‑2 vehicles). | `200 OK`, array size matches expected subset. |
| **E‑003** | `/vehicles` | GET | `page=-1&size=10` | **Edge** | Negative pagination values. | `400 Bad Request` with pagination‑parameter error. |
| **B‑004** | `/vehicles` | GET | `page=0&size=0` | **Boundary** | Zero‑size page request. | `400 Bad Request` (size must be ≥1) or `200 OK` with empty list, per spec. |
| **B‑005** | `/vehicles` | GET | `page=1&size=1000` | **Boundary** | Very large page size (exceeds max allowed). | `400 Bad Request` or `200 OK` with capped size (e.g., 200). |
| **H‑004** | `/vehicles` | GET | `page=2&size=50` | **Happy Path** | Normal pagination – second page of 50 items. | `200 OK`, `items.length == 50` (or remaining count on last page). |
| **E‑006** | `/vehicles` | GET | `sort=invalidField` | **Edge** | Sort by a non‑existent field. | `400 Bad Request` with clear error. |
| **H‑005** | `/vehicles` | GET | `sort=make,asc` | **Happy Path** | Valid sorting parameter. | `200 OK`, list ordered by `make` ascending. |
| **C‑001** | `/vehicles` | GET | `status=ACTIVE` (no pagination) | **Concurrency** | Fire **100 concurrent** requests from different clients. | All responses return `200 OK` within SLA; no data corruption or throttling errors. |
| **C‑002** | `/healthz` | GET | – | **Concurrency** | Spike of **500 health‑check** calls per second for 30 s. | Service consistently returns `200`/`503` as appropriate; no socket‑timeouts. |
| **C‑003** | `/vehicles` | GET | `status=ACTIVE&page=1&size=20` | **Concurrency + Rate‑Limit** | Run 5 threads each issuing 200 requests (total 1 000) to verify rate‑limit headers (`X‑RateLimit‑Remaining`). | Responses respect configured limits (e.g., 429 Too Many Requests after threshold). |
| **E‑007** | `/vehicles` | GET | `status=%3Cscript%3Ealert(1)%3C/script%3E` | **Security / Edge** |
