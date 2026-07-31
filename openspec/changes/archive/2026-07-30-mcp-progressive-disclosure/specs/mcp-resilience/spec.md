# mcp-resilience Specification Delta

## MODIFIED Requirements

### Requirement: MCP discovery metadata does not expose known secrets
ForgeAgent MUST apply the existing sensitive-environment value policy before discovered MCP metadata or configured server identity reaches the model prompt, CLI, ToolOutcome feedback, structured call errors, public status, required-startup diagnostics or lifecycle logs. JSON-like input schemas MUST be recursively masked; exact built-in floats MUST be finite, and any nested NaN, positive infinity or negative infinity MUST make the public schema `{}`; a masked key collision or any other non-JSON-like value MUST have the same result. A tool or configured server routing identity that contains a known secret MUST NOT be advertised because a masked display alias cannot be routed safely back to the original SDK identity. Public configured-server labels MUST be stable and collision-free; an unknown or manually supplied raw server identity MUST map to one manager-owned fixed category label allocated without collision against configured public labels and never derived from that raw input. Internal lifecycle, approval and call routing MUST continue to use the original identity. The bounded MCP directory and `MCPDescribe` detail projection MUST use the same masked public snapshot and MUST NOT introduce an alternate raw metadata path.

#### Scenario: Tool description contains a known secret
- **WHEN** MCP discovery returns a tool whose description contains a known sensitive environment value
- **THEN** the catalog, generated tools prompt, `MCPDescribe` detail and `/mcp` listing contain the redaction marker instead of the secret while preserving the safe tool name and its original call routing

#### Scenario: Input schema contains a known secret
- **WHEN** MCP discovery returns a JSON-like `inputSchema` whose keys or string values contain a known sensitive environment value
- **THEN** ForgeAgent recursively masks those keys and values before returning the catalog or `MCPDescribe` detail; if masking makes the schema structurally ambiguous or a non-JSON-like value is present, it returns an empty public schema instead of raw data

#### Scenario: Tool name contains a known secret
- **WHEN** MCP discovery returns a tool whose name would change under known-secret masking
- **THEN** ForgeAgent excludes that tool from the available catalog, directory and `MCPDescribe` lookup instead of advertising a non-routable masked alias

#### Scenario: Server identity contains a known secret
- **WHEN** a configured server identity would change under known-secret masking
- **THEN** ForgeAgent excludes that server's tools from the available catalog and directory, uses the same public label in status, required-startup, `/mcp`, `MCPDescribe`, ToolOutcome, structured error and lifecycle log output, and retains the original identity only for internal lifecycle, approval and call routing

#### Scenario: Redacted server labels collide
- **WHEN** two raw server identities mask to the same text or collide with an already-safe configured identity
- **THEN** ForgeAgent preserves every safe raw label, assigns deterministic non-secret numeric suffixes to the redacted identities, reports every status/failure without overwrite, and lets enable/disable feedback select the exact raw server's public label

#### Scenario: Manual or replayed MCP call contains a known secret
- **WHEN** a ToolCall supplies a secret-bearing server or tool identity even though it was not advertised
- **THEN** approval and call routing receive the raw identity while the next-round feedback and CLI outcome contain only the manager-owned public server label and masked tool label
