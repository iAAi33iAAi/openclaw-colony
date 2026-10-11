# Biometric Scanner Attestation Protocol

This document specifies the request-signing format expected by OpenClaw Colony's
`POST /biometric/attest` endpoint. It is intended for trusted scanner firmware
or a scanner-side gateway. Do not put scanner secrets in browser code.

## Configuration

The server setting `COLONY_SCANNER_KEYS` is a JSON object mapping each
`scanner_id` to a unique random secret of at least 32 characters. Store each
secret only in that scanner/gateway and the server's secret manager. The server
rejects missing keys and obvious placeholder values.

The request body must include every field, including default-valued fields:

- `scanner_id`
- `badge_serial`
- `face_scan_hex`
- `retina_scan_hex`
- `liveness_score`
- `location_node`
- `action_type`

Use the same field values for signing and for the HTTP body.

## Canonical signed bytes

1. Serialize the complete request body to UTF-8 JSON with lexicographically
   sorted keys, no whitespace separators, ASCII escaping enabled, and
   non-finite numbers forbidden. Equivalent Python serialization:

   ```python
   body = json.dumps(
       payload,
       sort_keys=True,
       separators=(",", ":"),
       ensure_ascii=True,
       allow_nan=False,
   )
   ```

2. Take the decimal Unix timestamp in seconds as an ASCII string and the
   request nonce as a UTF-8 string. The nonce must contain between 16 and 128
   characters. Generate a cryptographically random nonce for every request.

3. Construct the exact message bytes:

   ```python
   message = (
       timestamp.encode("ascii")
       + b"\n"
       + nonce.encode("utf-8")
       + b"\n"
       + body.encode("utf-8")
   )
   signature = hmac.new(
       scanner_secret.encode("utf-8"),
       message,
       hashlib.sha256,
   ).hexdigest()
   ```

   The delimiters are two actual line-feed bytes (0x0A), not the two-character
   sequence backslash + `n`.

4. Send the same body and these headers:

   - `X-Scanner-Timestamp: <decimal Unix seconds>`
   - `X-Scanner-Nonce: <unique random nonce>`
   - `X-Scanner-Signature: <64-character lowercase HMAC-SHA256 hex digest>`

The timestamp must be within 30 seconds of server time. The nonce is persisted
before biometric token issuance and may be accepted only once. A rejected scan
still consumes its request nonce; retry using a new timestamp and nonce and
re-sign the unchanged or corrected payload.

## Important trust boundary

This signature authenticates the submitted scanner claims and prevents request
tampering/replay. It does not by itself prove that a physical sensor measured
the claimed liveness score correctly. The deployed scanner firmware, sensor
path, key storage, firmware-update process and physical access controls require
their own security validation. Requests that cannot authenticate fail closed.
