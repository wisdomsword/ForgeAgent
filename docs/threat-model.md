# Threat Model

This document states the current runtime boundaries, not a guarantee that untrusted code is safe on every host. Select the execution tier according to task-source trust and consequence.

## Execution tiers

- `trusted`: same-process execution with no isolation. Treat model-generated code as fully trusted.
- `restricted`: a new subprocess per block with application-layer path, network, process, timeout, and resource restrictions. It is not an OS security boundary.
- `container`: a hardened Docker container per block. It provides stronger OS-level isolation but is not a virtual machine or protection against host/kernel compromise.

## Direct-only network boundary

`WebFetch` and `/search` are direct-only. `guarded_urlopen()` builds its opener with `ProxyHandler({})`, so uppercase and lowercase `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` values are not used. `NO_PROXY` and `no_proxy` cannot restore a removed proxy handler.

The guard accepts only HTTP(S), validates every resolved candidate address (including NAT64 embedded IPv4), connects to the already-vetted sockaddr to avoid DNS-rebinding between validation and connection, and applies the same validation on every redirect hop. It allows at most 10 redirects; the eleventh is rejected before opening its target.

**[SECURITY][BREAKING] Enterprise proxy compatibility:** a deployment that requires an environment proxy for egress will no longer make WebFetch or `/search` work through that proxy. The only supported migration paths are:

1. Allow this process to make direct outbound connections.
2. Prefetch externally using a trusted system, place the material under `allowed_root`, and use `FileRead`.
3. Configure an explicitly trusted MCP fetch tool and accept that MCP tool's separate trust boundary.

Do not restore environment proxies as a workaround. There is no `network.proxy` setting in the current release. A future explicit proxy feature must use either a trusted-forward-proxy model, where the proxy is the trusted egress/SSRF boundary, or a guarded-tunnel model that preserves ForgeAgent's vetted-target guarantee.

## Web and file tools

`WebFetch` is GET-only. In `restricted` and `container`, its confirmation gate is a real network boundary because executed code cannot open sockets directly. `FileWrite` confirmation is UX only: code executed in those tiers may already write anywhere under `allowed_root`. FileRead and FileList use the same root boundary but do not require approval.

WebFetch and File tools canonicalize both `allowed_root` and the target with `realpath()`, then use platform-aware `commonpath()` containment. This blocks static symlink escapes and allows the root itself, including `allowed_root="/"`. A failed path operation is deliberately reduced to a fixed outcome (`WebFetch blocked by network policy`, `WebFetch request failed`, `WebFetch response save failed`, `FileRead failed`, `FileWrite failed`, `FileWrite path is outside project root`, or `FileList failed`) where appropriate, preventing URL, hostname, exception, or absolute-path disclosure through feedback and CLI output.

Residual TOCTOU risk remains: an external concurrent actor can replace the validated target or an ancestor path component with a symlink between canonicalization and pathname-based open. This can affect trusted code, an MCP process, or another host process. ForgeAgent does not claim that File tools resist this component-replacement race; eliminating it requires descriptor-based, platform-specific APIs outside the current portable design.

## MCP boundary and lifecycle

MCP servers are user-configured host processes outside the executor sandbox. Only configure executables and `autoApprove` entries you trust. `autoApprove` is a per-server/tool explicit approval and can run without a TTY; other MCP, WebFetch, and FileWrite approvals require both stdin and stdout to be TTY-capable. Non-TTY operation rejects the call without reading confirmation input. `--interactive` affects Survey, not this policy.

Each MCP server is optional by default (`required: false`). Optional startup failures degrade: their tools are omitted while the CLI remains usable with a sanitized server-specific status. An enabled `required: true` server that fails aborts startup after cleanup and returns non-zero.

MCP uses a named daemon loop thread and one loop-owned shutdown drain. `close()` uses a single absolute deadline for its public wait, cancellation, and join budget. If cleanup cannot finish, ForgeAgent returns control, warns that shutdown is incomplete, keeps the shutdown task/future and holder, session, loop, and thread references for a later retry, and does not fabricate completion. The warning reports only thread state and sanitized pending server names: it does not capture stacks, arguments, environment values, or server content. A daemon thread can still temporarily retain transports, file descriptors, or child processes when underlying code is stuck.

## Completion and information flow

A model response with a tool call or parser error cannot complete the task in that same round. The result must be observed by a subsequent clean, explicit completion response. This avoids treating a statement produced before tool output as verified completion.

Web content, MCP output, and tool feedback are untrusted input. Secrets are masked where data is rendered, but masking is not an authority boundary. Keep credentials out of prompts, task files, and model-accessible directories.
