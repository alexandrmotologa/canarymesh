# Routing strategies

CanaryMesh determines the destination of each request using an ordered evaluation process.

## Evaluation order

When a request arrives, CanaryMesh evaluates routing criteria in the following sequence:

1. **Query parameter override**:
   If the query string contains `canary=true` or `canary=1`, the request goes to the canary service. If it contains `canary=false` or `canary=0`, it goes to the stable service.

2. **Canary header override**:
   If the request header `X-Canary` is set to `true`, `1`, or `yes`, the request routes to the canary service. If set to `false`, `0`, or `no`, it routes to the stable service.

3. **Pattern header rules**:
   Custom rules configured in settings or YAML are evaluated against headers. For example, a rule matching `X-User-Group: beta-.*` directs matching traffic to the canary service.

4. **Sticky cookie session**:
   If a `canary_session` cookie is present, CanaryMesh calculates a hash of the session string modulo 100. If the resulting bucket number is lower than the active canary weight percentage, the request goes to the canary service. Otherwise, it routes to stable.

5. **Random distribution**:
   If no session cookie exists, CanaryMesh generates a new session token, applies the hash bucket calculation, routes the request, and sets the `canary_session` cookie on the client response.

## Consistent session hashing

CanaryMesh uses MD5 modulo 100 to map session identifiers to an integer between 0 and 99:

```python
bucket = int(hashlib.md5(session_id.encode("utf-8")).hexdigest(), 16) % 100
```

When canary traffic increases from 10% to 25%, users assigned to buckets 0 through 9 remain on the canary service, while users in buckets 10 through 24 move from stable to canary. Users do not flap back and forth during weight changes.
