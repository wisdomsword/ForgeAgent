## ADDED Requirements

### Requirement: Headless authorization uses exact typed operation keys

Headless mode MUST validate static allowlist entries as exact typed operation keys. WebFetch keys MUST use the versioned form `web/v1/<scheme>/<host>/<port>/<path>/<query-digest>`, where `query-digest` is a fixed-length digest of the raw query string. The implementation MUST normalize scheme, host, port, and path as before, MUST NOT sort, decode, or re-encode the query before digesting it, and MUST reject legacy WebFetch keys that omit the version or query digest. Persisted authorization keys and audit operation keys MUST NOT contain the query plaintext.

#### Scenario: Same path with a different query is denied

- **WHEN** the allowlist contains a key generated for `https://example.com/a?account=public`
- **THEN** WebFetch for `https://example.com/a?account=admin&include_secrets=true` is denied
- **AND** the authorization key contains only the fixed-length query digest, not either query plaintext.

#### Scenario: Redirect effective URL is reauthorized with query binding

- **WHEN** an authorized WebFetch URL redirects to the same origin and path with a different query
- **THEN** the redirect is rejected before its request is sent.
