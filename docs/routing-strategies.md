# Routing strategies

CanaryMesh determines the destination of each request using an ordered evaluation process across HTTP and WebSocket streams.

## Evaluation order

When a request arrives, CanaryMesh evaluates routing criteria in the following sequence:

1. **Path prefix rules**:
   If the request URL path starts with a registered path prefix (for example `/api/v2/*` or `/checkout`), the request routes to the designated target (`canary` or `stable`).
   Path rules can be configured in settings or added dynamically at runtime via `POST /api/v1/canary/rules/path`.

2. **Query parameter override**:
   If the query string contains `canary=true` or `canary=1`, the request goes to the canary service. If it contains `canary=false` or `canary=0`, it goes to the stable service.

3. **Canary header override**:
   If the request header `X-Canary` is set to `true`, `1`, or `yes`, the request routes to the canary service. If set to `false`, `0`, or `no`, it routes to the stable service.

4. **Pattern header rules**:
   Custom rules evaluated against request headers. For example, a regex rule matching `X-User-Group: beta-.*` or `X-Tier: internal` directs matching traffic to the canary service.
   Header rules can be created dynamically via `POST /api/v1/canary/rules/header`.

5. **Sticky cookie session**:
   If a `canary_session` cookie is present, CanaryMesh calculates a hash of the session string modulo 100. If the resulting bucket number is lower than the active canary weight percentage, the request goes to the canary service. Otherwise, it routes to stable.

6. **Random distribution**:
   If no session cookie exists, CanaryMesh generates a new session token, applies the hash bucket calculation, routes the request, and sets the `canary_session` cookie on the client response.

## Consistent session hashing

CanaryMesh uses MD5 modulo 100 to map session identifiers to an integer between 0 and 99:

```python
bucket = int(hashlib.md5(session_id.encode("utf-8")).hexdigest(), 16) % 100
```

When canary traffic increases from 10% to 25%, users assigned to buckets 0 through 9 remain on the canary service, while users in buckets 10 through 24 move from stable to canary. Users do not flap back and forth during weight changes.

## Runtime dynamic routing rules

### Path prefix rules

Add a path prefix rule on the fly:

```bash
curl -X POST http://localhost:8090/api/v1/canary/rules/path \
  -H "Content-Type: application/json" \
  -d '{"path_prefix": "/checkout", "target": "canary"}'
```

### Header match rules

Add a regex header match rule on the fly:

```bash
curl -X POST http://localhost:8090/api/v1/canary/rules/header \
  -H "Content-Type: application/json" \
  -d '{"header_name": "x-user-group", "header_pattern": "beta.*|qa-testers", "target": "canary"}'
```

### View active rules

```bash
curl http://localhost:8090/api/v1/canary/rules
```

### Delete a rule

```bash
curl -X DELETE http://localhost:8090/api/v1/canary/rules/path/<rule_id>
curl -X DELETE http://localhost:8090/api/v1/canary/rules/header/<rule_id>
```
