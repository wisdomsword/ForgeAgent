# Threat Model

This document describes current boundaries and residual risk. It does not claim
that model-generated code is safe on a hostile host or that a daemon thread can be
force-killed safely.

## Assets and trust boundaries

Assets include API keys and sensitive environment values, files under and outside
`allowed_root`, outbound network access and private addresses, model/task history,
MCP tool descriptions and results, MCP child processes/transports, and terminal
approval decisions. Model output, WebFetch content, MCP content, search results,
and tool feedback are untrusted data, not instructions.

Execution tiers are explicit:

- `trusted`: same-process `exec()`, persistent globals, no isolation. Use only for
  fully trusted task sources; the user accepts all host access risk.
- `restricted` (default): one subprocess per block, application-layer audit hooks,
  canonical path/network restrictions, Unix `rlimit` where available, and timeout
  kill. It is not an OS security boundary; Python/native escape techniques and a
  hostile host remain outside its guarantee.
- `container`: one Docker container per block, only `allowed_root` mounted read/write,
  no network, non-root, dropped capabilities, no-new-privileges, read-only rootfs,
  resource limits, and timeout `docker kill`. It is stronger OS isolation, not a VM;
  kernel/Docker escape and basic `/proc` information remain possible.

`MCP` servers are configured host processes in the main process, outside executor
isolation. They are a separate user-trust boundary. WebFetch and `/search` are main
process network paths; executor code in restricted/container has no network broker.

## Threats, mitigations, and residual risk

| ID | Threat | Current mitigation | Residual risk |
| --- | --- | --- | --- |
| T1 | Secret read, echo, or external disclosure | Restricted/container executor scrubs sensitive env values; audit hooks restrict file reads; executor output, errors, FileRead, WebFetch previews, MCP results, and MCP discovery descriptions/schema strings are value-masked with `mask_secrets()`; secret-bearing MCP routing identities are not advertised, and one stable collision-free public label is used for MCP status, startup diagnostics, ToolOutcome feedback and lifecycle logs. | Masking is defense in depth, not an authority boundary. Trusted code, MCP, host processes, or a secret not covered by the naming/value policy may still access it. |
| T2 | Write outside the project or overwrite host files | Executor audit hooks and File tools resolve `allowed_root` and target with `realpath()` and check `commonpath()` containment. FileWrite gives a fixed failure for escapes. | FileWrite confirmation is UX only: Exec can already write inside `allowed_root`. Hostile concurrent replacement can create pathname races. |
| T3 | Executor data exfiltration or private-network access | Restricted/container audit hooks reject socket/network operations; container also uses `--network none`. No executor network broker exists. | Restricted is Python application-layer enforcement and may be bypassed by native/OS techniques; trusted has no mitigation. |
| T4 | Package installation / supply-chain or resource abuse | There is no runtime package installer or confirmation workflow. In restricted, `pip install` is blocked by process-spawn and network denials; container has no network and uses a fixed image. | Trusted has no package-install protection; preinstalled container packages and trusted host tooling remain user responsibility. No package signing or multi-tenant isolation. |
| T5 | Prompt injection in external data | External data is framed as data, not instructions; it never relaxes executor limits or approval policy. | The model can still be persuaded to produce harmful but policy-permitted actions; correctness is not a security property. |
| T6 | Infinite loop, daemonization, fork, or resource exhaustion | One subprocess/container per block, timeout kill, restricted audit hooks that deny process spawning, and Unix `rlimit` for CPU and address space where supported. | Windows lacks the Unix CPU/address-space limits; file descriptors and process counts are not directly limited by `rlimit`, and native/kernel work and trusted same-process code are not reliably bounded. |
| T7 | Bypass of AST import/static checks | Static analysis is advisory only; backend audit hooks and process boundaries are the enforcement layer. | AST rules can be bypassed and restricted hooks are not a sealed OS sandbox; container is the stronger option. |
| T8 | MCP server/tool executes host-side side effects | Servers are explicit user configuration; MCP calls use per-`(server, tool)` `autoApprove` or a confirmer. Missing/non-TTY confirmation rejects; disabled/unavailable servers and secret-bearing discovered tool names are not advertised. Tool descriptions are marked external data and known secret values are masked in descriptions/results. | T8 is outside the executor sandbox. An approved MCP server runs with host permissions and can access network/files. Do not treat MCP as restricted/container code. |
| T9 | Container escape or host information leakage | Docker container uses no network, limited mount, non-root, dropped caps, no-new-privileges, read-only rootfs, resource limits, `/sys` masking, and empty inherited environment. | Kernel/Docker vulnerabilities are not mitigated. Basic `/proc` CPU/memory/kernel/network metadata remains visible. No VM guarantee. |
| T10 | WebFetch SSRF or File canonical-path escape | WebFetch is direct-only through `ProxyHandler({})`; only HTTP(S), every resolved candidate and redirect hop is checked, NAT64 embedded IPv4 is checked, vetted sockaddr is connected directly, and redirects are capped at 10. File/WebFetch targets use canonical `realpath()` plus `commonpath()` and fixed outcomes. | The direct-only behavior is a `[SECURITY][BREAKING]` proxy change: env proxies and `NO_PROXY` do not restore proxying. Canonicalization blocks static symlinks but does not solve hostile-host TOCTOU between validation and pathname open. |
| T11 | Search abuse or streaming partial-protocol corruption | `/search` URL host is fixed, query is encoded, and it reuses the SSRF guard; results are printed only, not injected into task history. Streaming failures after any delta become one `ClientError`, require terminal provider completion, and discard partial text. | Search HTML is best-effort and external content may contain injection. Streaming/native-call aggregation can still fail as a normal client error; no partial result is treated as verified. |
| T12 | Identity file path/size/TOCTOU and persistent trust bypass | User-level `SOUL.md`/`USER.md` under `home` and project-level `AGENTS.md`/`MEMORY.md` under `<allowed_root>/.forgeagent` are resolved with `realpath()` plus `commonpath()` containment before read; containment checks cover both the `.forgeagent` directory and each target file. Each file is capped at 32 KiB and the combined masked content at 96 KiB. Unsafe, unreadable, or oversized SOUL.md/USER.md content raises IdentityConfigError and stops identity resolution. Unsafe or oversized AGENTS.md/MEMORY.md content is stripped with a masked diagnostic, while an unreadable AGENTS.md or MEMORY.md raises IdentityConfigError and stops identity resolution. A versioned, atomically-written trust record (`~/.forgeagent/identity-trust.json`) binds a canonical project identity to the raw content digest and the masked effective-input digest, so file-byte or effective-mask changes invalidate prior trust and force reconfirmation. Missing records are unconfirmed; malformed, unknown-version, structurally invalid, or unreadable records are treated as unconfirmed and never overwritten. `--no-identity` disables all custom identity files while keeping the fixed protocol and MCP tool description sections intact. M15 loads authored identity files; M18 additionally parses only its controlled MEMORY entries and never executes free-form Markdown. G381-G420 remain candidate definitions, not passed verification. | Digest binding detects content drift after the read; it does not close the residual path-check/read race on a hostile multi-writer host, the same residual class as T10's File/WebFetch canonicalization. A fully authorized, user-approved `SOUL.md`/`AGENTS.md` can still steer the model toward policy-permitted but unwanted behavior — this is the T5 class of risk, not something size caps or masking prevent. Losing or deleting `identity-trust.json` forces reconfirmation but is not itself a security failure. |
| T13 | Unauthenticated or over-privileged local HTTP task control | `serve` is opt-in and server-owned; startup requires a static bearer token and loopback bind, every request uses exact bearer authentication, request fields are strict, and responses use a bounded safe projection. HTTP confirmation uses exact typed allowlist keys and explicitly disables MCP `autoApprove` inheritance. Audit startup fails closed; runtime write failures are marked degraded. | This is a local single-user boundary, not TLS or multi-tenant isolation. A process with local access to the token can submit/cancel tasks. FileWrite validation/open retains a symlink TOCTOU window; cooperative cancellation cannot interrupt an in-flight provider call; startup log compaction can read a whole old file; Unix path handling has no dedicated Windows UNC guarantee; a disconnect during error writing may produce a socketserver diagnostic traceback. |
| T14 | Unbounded prompt/tool feedback or misleading truncation | Every Task entry point uses a server/client-owned, local approximate-token sliding view. System prompt, initial goal, and complete assistant + feedback units are never rewritten; impossible prefix/latest-unit or fixed-feedback-metadata budgets fail before the next provider call. Truncated tool feedback states the original total, displayed range, and only a real continuation, while full outcomes remain local. | Approximate estimation can slide earlier than a provider tokenizer would, and may still miss a provider context-length limit; that returns a structured client error. Context limiting does not make untrusted tool data safe or expand the restricted/container boundary, and M16 HTTP request, allowlist, safe projection, cancellation, and audit semantics remain unchanged. |
| T15 | Memory poisoning or cross-task leakage | Model candidates and `/remember` input pass a deterministic gate: only fact/preference/decision kinds, bounded keys/content, control-character/secret checks, and finite prompt-injection patterns are admitted; procedure candidates are diverted to Skill. Project writes are atomic and last-writer-wins, `/memory` exposes masked entries, direct file edits correct them, and `--no-memory` disables both scopes. CLI owns one session store; HTTP creates a project-only store per task. | Rules are not semantic truth or a complete injection detector: an accepted false fact can influence later prompts until corrected or disabled. Memory is never an execution boundary; protocol, confirmation, sandbox, and audit controls remain authoritative. |

## Network breaking change

WebFetch and `/search` intentionally ignore uppercase/lowercase `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, and `no_proxy`. Deployments that require an
enterprise proxy must either allow direct egress, prefetch through a trusted system
and use `FileRead`, or configure a user-trusted MCP fetch tool. There is no current
`network.proxy` setting. A future proxy feature must define an explicit trusted
forward-proxy or guarded-tunnel boundary.

## MCP lifecycle residual

MCP uses one named daemon loop thread and generation-aware holder/session slots. Close
uses one absolute deadline, one loop-owned drain, bounded cancellation and join, and
repeatable close retries. If cleanup cannot finish, ForgeAgent returns control with a
sanitized `shutdown incomplete` warning, retains the shutdown task/future, holders,
sessions, loop, and thread references, and does not fabricate completion. A stuck
daemon thread may temporarily retain transports, file descriptors, or child
processes. Python has no safe API to kill that thread, so the implementation does
not claim forced termination. Pending server names and thread state may be reported;
arguments, environment values, stacks, and server content are not.

MCP generation tracking prevents stale holder/session cleanup from deleting a newer
generation, but it does not make an unresponsive SDK or child process disappear.
This is the documented incomplete-shutdown/generation residual, not a stronger
process isolation guarantee.
