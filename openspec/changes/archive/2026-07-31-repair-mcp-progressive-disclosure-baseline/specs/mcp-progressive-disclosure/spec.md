## ADDED Requirements

### Requirement: MCP prompt uses a bounded tool directory

ForgeAgent SHALL inject only a bounded MCP directory into the task system prompt. Each advertised entry MUST use the manager-owned public server label, tool name, one-line bounded summary, and a permission hint; the prompt MUST identify descriptions as external data and MUST explain that `MCPDescribe` can provide details on demand. Full input schemas MUST NOT be injected into this directory.

#### Scenario: Directory lists available tools
- **WHEN** one or more MCP tools are available
- **THEN** the system prompt lists each public server/tool pair with a bounded summary and tells the model how to request details

#### Scenario: Long discovery metadata is bounded
- **WHEN** a server returns a very long, multiline, or control-character-bearing description
- **THEN** the directory normalizes it to one line and truncates it within the configured summary limit

#### Scenario: No MCP tools are available
- **WHEN** no MCP tool is available
- **THEN** the MCP prompt section is empty and no detail lookup instruction is advertised

### Requirement: MCPDescribe returns one safe tool detail

ForgeAgent SHALL expose a read-only `MCPDescribe` tool with arguments `{server, tool}`. It MUST read only the current available manager-owned public discovery snapshot, return a bounded masked description and JSON-like input schema, and MUST NOT connect to a server, execute an external action, request confirmation, or create an external-action receipt.

#### Scenario: Known tool is described through the real manager
- **WHEN** `MCPDescribe` receives an available public server/tool pair through a real `MCPManager`
- **THEN** it returns the tool description, bounded input schema, and current approval hint without network, confirmation, or receipt side effects

#### Scenario: Unknown tool is requested
- **WHEN** the server/tool pair is absent or unavailable
- **THEN** the tool returns a failed structured outcome with a bounded retry instruction and does not access the MCP loop

#### Scenario: Detail metadata exceeds limits
- **WHEN** the description or schema exceeds its configured bound or cannot be serialized safely
- **THEN** the result remains bounded and uses an empty schema or truncation continuation instead of exposing raw data

#### Scenario: Duplicate detail requests are deterministic
- **WHEN** the same `{server, tool}` is requested repeatedly without a discovery change
- **THEN** each response is derived from the same snapshot and no new network, connection, confirmation, receipt, or external action occurs

### Requirement: Existing MCP calls and CLI diagnostics remain compatible

ForgeAgent SHALL keep the existing `MCP` ToolCall `{server, tool, arguments}` routing, confirmation, receipt, failure, and masking semantics unchanged. CLI `/mcp tools` MUST continue to display the complete available masked discovery listing, independent of the bounded system-prompt directory.

#### Scenario: Existing MCP call remains routable
- **WHEN** the model calls an advertised tool through `MCP`
- **THEN** the original internal server/tool identity reaches existing routing and the existing confirmation and receipt policy applies

#### Scenario: CLI requests full listing
- **WHEN** a user runs `/mcp tools`
- **THEN** the CLI displays the complete masked descriptions and existing diagnostic fields from the manager while schema remains available through `MCPDescribe`
