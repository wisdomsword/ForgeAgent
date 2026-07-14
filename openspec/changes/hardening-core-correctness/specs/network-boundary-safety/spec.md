## ADDED Requirements

### Requirement: Web requests ignore environment proxies by default
ForgeAgent SHALL make WebFetch and `/search` requests through an explicitly direct connection path and SHALL NOT consume proxy settings from process environment variables.

#### Scenario: HTTP proxy is present
- **WHEN** `HTTP_PROXY`, `HTTPS_PROXY` or `ALL_PROXY` points to a reachable proxy and no ForgeAgent-specific proxy capability is implemented
- **THEN** WebFetch and `/search` connect directly through the SSRF guard and never send the request to that proxy

#### Scenario: Lowercase proxy variables are present
- **WHEN** lowercase proxy environment variables are configured
- **THEN** they do not alter WebFetch or `/search` routing

### Requirement: Every effective target is SSRF validated
ForgeAgent MUST validate the effective destination of the initial request and every redirect hop using the existing blocked-address rules before opening the corresponding connection.

#### Scenario: Initial target resolves to a blocked address
- **WHEN** a request target resolves to loopback, private, link-local or another address forbidden by the threat model
- **THEN** ForgeAgent rejects the request before transmitting application data

#### Scenario: Redirect reaches a blocked address
- **WHEN** an allowed public URL redirects to a forbidden destination
- **THEN** ForgeAgent rejects the redirect before connecting to the forbidden destination

#### Scenario: NAT64 representation maps to a blocked IPv4 address
- **WHEN** a target resolves to a NAT64 address whose embedded IPv4 address is forbidden
- **THEN** ForgeAgent applies the forbidden-address result and rejects the request

### Requirement: Redirect processing is bounded and scheme restricted
ForgeAgent MUST maintain its own maximum of 10 redirect hops and MUST reject any redirect whose resolved scheme is not HTTP or HTTPS.

#### Scenario: Redirect chain exceeds the hard limit
- **WHEN** a response chain attempts an eleventh redirect
- **THEN** ForgeAgent raises an explicit SSRF guard error identifying that the redirect limit was exceeded before opening the eleventh destination

#### Scenario: HTTP response redirects to a non-HTTP scheme
- **WHEN** an HTTP or HTTPS response redirects to FTP, file or another unsupported scheme
- **THEN** ForgeAgent rejects the redirect before any handler for that scheme can access the destination

### Requirement: Proxy support remains explicit and disabled
ForgeAgent SHALL document that future proxy routing requires a ForgeAgent-owned configuration contract and MUST NOT treat operating-system or environment proxy configuration as that contract.

#### Scenario: User needs proxy routing during this milestone
- **WHEN** a user configures only system or environment proxy settings
- **THEN** ForgeAgent continues to use direct guarded connections and documentation states that explicit proxy forwarding is not implemented

### Requirement: Guarded web consumers contain expected protocol failures
ForgeAgent MUST convert expected URL, transport, HTTP protocol and response-decoding failures into each consumer's stable result contract and MUST NOT let those failures escape as uncaught exceptions.

#### Scenario: WebFetch receives an incomplete or malformed HTTP response
- **WHEN** a confirmed WebFetch request raises `http.client.HTTPException` while opening, reading or closing the response
- **THEN** WebFetch returns the fixed detail `WebFetch request failed` without exception text, URL or hostname

#### Scenario: WebFetch receives an invalid model URL
- **WHEN** a confirmed WebFetch request raises `ValueError` or `http.client.InvalidURL` while constructing or opening the request
- **THEN** WebFetch returns the fixed detail `WebFetch request failed` without propagating the exception

#### Scenario: Search receives an HTTP protocol failure
- **WHEN** `/search` encounters `OSError` or `http.client.HTTPException` while opening, reading or closing the response
- **THEN** it returns the existing unavailable status instead of raising

#### Scenario: Search receives an unknown response charset
- **WHEN** a successful search response declares a charset unavailable to Python
- **THEN** ForgeAgent decodes the response with UTF-8 replacement semantics and continues best-effort parsing
