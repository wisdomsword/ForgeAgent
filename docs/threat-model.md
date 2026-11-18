# Threat Model

This document describes current boundaries and residual risk. It does not claim
that model-generated code is safe on a hostile host or that a daemon thread can be
force-killed safely.

## Assets and trust boundaries

Assets include API keys and sensitive environment values, files under and outside
`allowed_root`, outbound network access and private addresses, model/task history,
MCP tool descriptions and results, MCP child processes/transports, and terminal
approval decisions. Short-lived HTTP action approvals and durable external-action
receipts are separate host-owned authorities. Model output, WebFetch content, MCP content, search results,
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

开发期治理门禁（Prompt/Skill 退出条件、Memory 来源/可见性/更正、Rewrite 六项指标）以
[`docs/agent-governance-gates.md`](agent-governance-gates.md) 为 canonical 文档；缺少 verifier、来源不明或无回滚证据的变更不得进入实施。该门禁是流程约束，不替代运行时安全边界。

| ID | Threat | Current mitigation | Residual risk |
| --- | --- | --- | --- |
| T1 | Secret read, echo, or external disclosure | Restricted/container executor scrubs sensitive env values; audit hooks restrict file reads; executor output, errors, FileRead, WebFetch previews, MCP results, and MCP discovery descriptions/schema strings are value-masked with `mask_secrets()`; secret-bearing MCP routing identities are not advertised, and one stable collision-free public label is used for MCP status, startup diagnostics, ToolOutcome feedback and lifecycle logs. | Masking is defense in depth, not an authority boundary. Trusted code, MCP, host processes, or a secret not covered by the naming/value policy may still access it. |
| T2 | Write outside the project or overwrite host files | Executor audit hooks and File tools resolve `allowed_root` and target with `realpath()` and check `commonpath()` containment. Restricted Exec may read the installed Python runtime prefixes needed for imports, but write and mutation operations are limited to `allowed_root`; FileWrite additionally opens the canonical root and every parent/final target through directory descriptors with `O_NOFOLLOW`, verifies a regular final file, and rechecks the root binding before reporting success. FileWrite gives a fixed failure for escapes. | FileWrite confirmation is UX only: Exec can already write inside `allowed_root`. A hostile same-host writer can still move or remove the already-open original directory/file inode; ForgeAgent prevents following a replacement symlink but cannot roll back bytes written to that original inode. |
| T3 | Executor data exfiltration or private-network access | Restricted/container audit hooks reject socket/network operations; container also uses `--network none`. No executor network broker exists. | Restricted is Python application-layer enforcement and may be bypassed by native/OS techniques; trusted has no mitigation. |
| T4 | Package installation / supply-chain or resource abuse | There is no runtime package installer or confirmation workflow. In restricted, `pip install` is blocked by process-spawn and network denials; container has no network and uses a fixed image. | Trusted has no package-install protection; preinstalled container packages and trusted host tooling remain user responsibility. No package signing or multi-tenant isolation. |
| T5 | Prompt injection in external data | External data is framed as data, not instructions; it never relaxes executor limits or approval policy. | The model can still be persuaded to produce harmful but policy-permitted actions; correctness is not a security property. |
| T6 | Infinite loop, daemonization, fork, or resource exhaustion | One subprocess/container per block, configurable restricted timeout/CPU/address-space limits from shared config with CLI overrides, timeout kill, restricted audit hooks that deny process spawning, and Unix `rlimit` where supported. Limit failures preserve bounded stdout/stderr and map resource signals to stable human-readable feedback. | Windows lacks the Unix CPU/address-space limits; file descriptors and process counts are not directly limited by `rlimit`, and native/kernel work and trusted same-process code are not reliably bounded. |
| T7 | Bypass of AST import/static checks or restricted worker bootstrap | Static analysis is advisory only; backend audit hooks and process boundaries are the enforcement layer. Restricted launches its installed worker with Python isolated mode, so the task directory, user site-packages and `PYTHON*` path overrides cannot replace `forgeagent._sandbox_worker` or its runtime before the hook is installed. The installed runtime prefixes remain readable for imports, but restricted task code cannot write `sys.prefix` / `site-packages` or drop `.pth` bootstrap files there. | AST rules can be bypassed and restricted hooks are not a sealed OS sandbox; a compromised interpreter installation or native/kernel technique remains outside this boundary, and container is the stronger option. |
| T8 | MCP server/tool executes host-side side effects | Servers are explicit user configuration; MCP calls use per-`(server, tool)` `autoApprove` or a confirmer. Missing/non-TTY confirmation rejects; disabled/unavailable servers and secret-bearing discovered tool names are not advertised. Tool descriptions are marked external data and known secret values are masked in descriptions/results. | T8 is outside the executor sandbox. An approved MCP server runs with host permissions and can access network/files. Do not treat MCP as restricted/container code. |
| T9 | Container escape or host information leakage | Docker container uses no network, limited mount, non-root, dropped caps, no-new-privileges, read-only rootfs, resource limits, `/sys` masking, and empty inherited environment. | Kernel/Docker vulnerabilities are not mitigated. Basic `/proc` CPU/memory/kernel/network metadata remains visible. No VM guarantee. |
| T10 | WebFetch SSRF or File canonical-path escape | WebFetch is direct-only through `ProxyHandler({})`; only HTTP(S), every resolved candidate and redirect hop is checked, NAT64 embedded IPv4 is checked, vetted sockaddr is connected directly, and redirects are capped at 10. File/WebFetch targets use canonical `realpath()` plus `commonpath()` and fixed outcomes; FileWrite closes its validation/open symlink window with descriptor-relative `O_NOFOLLOW` traversal and final open. | The direct-only behavior is a `[SECURITY][BREAKING]` proxy change: env proxies and `NO_PROXY` do not restore proxying. FileRead, FileList, identity, Skill, evaluator snapshot, and WebFetch artifact pathname operations retain their separately documented hostile-host race classes; FileWrite does not claim rollback if the original opened inode is concurrently moved or removed. |
| T11 | Search abuse or streaming partial-protocol corruption | `/search` URL hosts are fixed, query is encoded, and each request independently reuses the SSRF guard. The preferred engine is tried first and the other built-in engine at most once after failure or zero results; results are printed only, not injected into task history. Streaming failures after any delta become one `ClientError`, require terminal provider completion, and discard partial text. | Both HTML parsers are best-effort and external content may contain injection; fallback doubles outbound requests only on the no-result/failure path. Streaming/native-call aggregation can still fail as a normal client error; no partial result is treated as verified. |
| T12 | Identity file path/size/TOCTOU and persistent trust bypass | User-level `SOUL.md`/`USER.md` under `home` and project-level `AGENTS.md`/`MEMORY.md` under `<allowed_root>/.forgeagent` are resolved with `realpath()` plus `commonpath()` containment before read; containment checks cover both the `.forgeagent` directory and each target file. Each file is capped at 32 KiB and the combined masked content at 96 KiB. Unsafe, unreadable, or oversized SOUL.md/USER.md content raises IdentityConfigError and stops identity resolution. Unsafe or oversized AGENTS.md/MEMORY.md content is stripped with a masked diagnostic, while an unreadable AGENTS.md or MEMORY.md raises IdentityConfigError and stops identity resolution. A versioned, atomically-written trust record (`~/.forgeagent/identity-trust.json`) binds a canonical project identity to the raw content digest and the masked effective-input digest, so file-byte or effective-mask changes invalidate prior trust and force reconfirmation. Missing records are unconfirmed; malformed, unknown-version, structurally invalid, or unreadable records are treated as unconfirmed and never overwritten. `--no-identity` disables all custom identity files while keeping the fixed protocol and MCP tool description sections intact. M15 loads authored identity files; M18 additionally parses only its controlled MEMORY entries and never executes free-form Markdown. G381-G420 remain candidate definitions, not passed verification. | Digest binding detects content drift after the read; it does not close the residual path-check/read race on a hostile multi-writer host, the same residual class as T10's File/WebFetch canonicalization. A fully authorized, user-approved `SOUL.md`/`AGENTS.md` can still steer the model toward policy-permitted but unwanted behavior — this is the T5 class of risk, not something size caps or masking prevent. Losing or deleting `identity-trust.json` forces reconfirmation but is not itself a security failure. |
| T13 | Unauthenticated or over-privileged local HTTP task control | `serve` is opt-in and server-owned; startup requires a static bearer token and loopback bind, every request uses exact bearer authentication, request fields are strict, and responses use a bounded safe projection. HTTP confirmation uses exact typed allowlist keys and explicitly disables MCP `autoApprove` inheritance. Audit startup fails closed; runtime write failures are marked degraded. FileWrite uses the same descriptor-relative final-open boundary as CLI/REPL. | This is a local single-user boundary, not TLS or multi-tenant isolation. A process with local access to the token can submit/cancel tasks. Cooperative cancellation cannot interrupt an in-flight provider call; startup log compaction can read a whole old file; Unix path handling has no dedicated Windows UNC guarantee; a disconnect during error writing may produce a socketserver diagnostic traceback. |
| T14 | Unbounded prompt/tool feedback or misleading truncation | Every Task entry point uses a server/client-owned, local approximate-token sliding view. System prompt, initial goal, and complete assistant + feedback units are never rewritten; impossible prefix/latest-unit or fixed-feedback-metadata budgets fail before the next provider call. Truncated tool feedback states the original total, displayed range, and only a real continuation, while full outcomes remain local. | Approximate estimation can slide earlier than a provider tokenizer would, and may still miss a provider context-length limit; that returns a structured client error. Context limiting does not make untrusted tool data safe or expand the restricted/container boundary, and M16 HTTP request, allowlist, safe projection, cancellation, and audit semantics remain unchanged. |
| T15 | Memory poisoning or cross-task leakage | Model candidates and `/remember` input pass a deterministic gate; procedure candidates are diverted to Skill. M42 project v2 records add host-owned source/writer/truth, visibility, lifecycle, recovery and correction metadata that model text cannot override. Expired, review-due and unknown legacy truth records stay stored but are excluded from prompt projection. Project read-modify-write uses a private lock, descriptor-bounded no-follow reads, atomic replacement and full write-after-read semantic verification. Legacy migration requires an exact operator manifest, creates a project-local `0700` directory with a `0600` recovery copy, and verifies the v2 result. Rollback is bound to the migration revision and rejects later writes with `rollback_conflict`. See [`docs/memory-migration.md`](memory-migration.md). | Admission and metadata are not semantic truth: an incorrect host assertion that has not expired or reached review time can still influence later prompts. `flock` is advisory and local-filesystem dependent; same-user hostile writers and unreliable network filesystems remain outside the guarantee. Backups contain the original plaintext Memory and remain until an operator deletes them. Memory is never an execution boundary; protocol, confirmation, sandbox and audit controls remain authoritative. |
| T16 | Project Skill prompt injection, content drift, or cross-request state | User Skills under `<home>/.forgeagent/skills/` are local user input. Project Skills under `<allowed_root>/.forgeagent/skills/` are confirmation-bound project input: the first interactive CLI use and every content change require a bounded, control-character-escaped, secret-masked name/trigger summary. The independent `<home>/.forgeagent/skills-trust.json` record binds the canonical project identity to both the raw-content digest and masked effective-input digest; a missing, malformed, unreadable, or changed record is unconfirmed. Only a bounded name/trigger catalog enters the initial prompt; the read-only `Skill` tool returns full content from an immutable CLI-session or HTTP-startup snapshot. Headless HTTP cannot confirm, so it excludes unapproved or changed project Skills. | Confirmation is not a permission grant or semantic safety proof: a user-approved Skill can still steer the model toward policy-permitted but unwanted actions. Secret masking is defense in depth and cannot protect unknown values. Path-check/read races on a hostile multi-writer host remain possible. Skill guidance cannot change the existing sandbox, tool-confirmation, audit, or two-stage Task-completion authority, and HTTP Tasks do not share mutable Skill execution state. |
| T17 | Evaluator artifact prompt injection, path escape, or context leakage | Evaluator artifact content is untrusted data, not instructions. `evaluate` is explicit opt-in and validates a canonical relative POSIX manifest under one non-symlink root, with fixed file/count/total-size bounds, then copies only declared files into a one-shot snapshot. It creates a fresh restricted Task over that snapshot with only FileRead/FileList and no Generator conversation, Memory, project Skills, MCP, audit sink, Exec, write, or network tools. Request/result text is bounded, secret-masked, control-escaped, and stripped of absolute path tokens; provider and task failures use fixed public text. | Model judgement is semantically non-deterministic and prompt injection can still affect its pass/fail opinion. The restricted tier is application-layer isolation, not a sealed OS boundary; source files retain a same-host modification window before snapshot copy. Known-secret and absolute-path masking cannot identify every sensitive semantic value. |
| T18 | Loop checkpoint injection, path escape, commit race, or replayed side effect | Checkpoint uses strict `forgeagent.loop.v1` validation with forbidden extra fields, bounded/control-safe text, supported version checks, allowed-root containment, symlink rejection, directory-file-descriptor writes, atomic replacement, and revision matching. Each Loop ID has a stable private lock file; create existence checks and save revision checks run under `flock(LOCK_EX)` with the atomic replacement, so overlapping ForgeAgent processes cannot both commit the same creation or old revision. Resume treats checkpoint text as untrusted framed data and retains the current CLI/server execution policy; public reports/audit events omit checkpoint body and host path. A successful model Checkpoint is a durable commit boundary, and an active HTTP resume ID is held by one service record. | `flock` is advisory and local-filesystem dependent; hostile writers that ignore it and network filesystems with unreliable locking remain outside the guarantee. A lock serializes commits but does not prevent two runners from duplicating provider/tool work before one checkpoint save becomes stale. Work after the last commit can replay after a crash, including external side effects; checkpointing is not exactly-once delivery. Prompt framing/masking cannot make untrusted handoff semantically safe. |
| T19 | Collaboration plan downgrade, cross-role prompt injection, Evaluator mutation, unsafe or stale check evidence, state path replacement, headless approval bypass, routing bypass, or model-call cost amplification | Planner, Generator and Evaluator use fresh Task/client/runtime/registry instances and receive cross-role material as bounded framed task data. `SubmitPlan` requires unique WHAT-only acceptance items; confirmation freezes order, text and plan digest. Generator can enter Evaluator only through revision-checked `SubmitCandidate`; Evaluator decides completion with exact-ID structured verdicts and a default read-only registry (`FileRead`, `FileList`, `SubmitEvaluation`) under restricted/container tier. Successful Submit tools immediately terminate their role, so prose or `task_status` cannot bypass the structured boundary. A trusted host may additionally inject frozen `RunCheck` definitions; the model supplies only an ID, while the current-Python invocation, env and timeout remain host-owned. Checks omit the project root's local agent/workflow metadata directories (`.agent`, `.agents`, `.claude`, `.codegraph`, `.codex`, `.superpowers`) alongside the existing repository/cache/build exclusions, but only when those six root entries are real directories; same-named nested directories and same-named top-level non-directories remain part of the Candidate. Checks reject every symlink and special file in the remaining Candidate tree, copy that tree to a temporary directory, then execute through a restricted audit-hook worker that denies outside-copy file-content access, directory enumeration and path mutation, plus every `socket.*`, spawn, fork, exec and process-signal-control audit event. Each result is bound to the current Generator attempt and the deterministic snapshot of the files actually copied; an all-pass verdict requires every frozen check to have a latest passed result for one snapshot that still matches the current Candidate. Missing, failed, stale, mixed-snapshot, modified-after-check, or recovered process-local evidence fails closed without saving the verdict. To import host-installed check dependencies, only the check worker may read and enumerate its current Python runtime prefixes and access the exact platform null device used by capture; ordinary restricted execution keeps the stricter default, and other host directories/devices remain denied. The parent uses no shell or credentials, drains output with a fixed in-memory head/tail cap, and terminates the POSIX process group on timeout/cancel. The symlink-safe, revision-checked `forgeagent.collaboration.v1` store uses a fixed directory fd and atomic replacement; each collaboration ID has a stable private lock file, and create existence checks plus save revision checks run under `flock(LOCK_EX)` with replacement, so overlapping ForgeAgent processes cannot both commit the same creation or old revision. Interactive Triad requires explicit plan approval; headless defaults to deny and only server-owned `preauthorize` can approve. The default route is Single; explicit modes take priority. Only a trusted host with non-empty frozen checks may supply the `has_bound_checks` boolean fact for automatic Triad, and that fact never comes from client task options or task text. `allow_weaker_override` is compatibility-only and has no routing behavior. Rejection count is capped, and public reports/audit contain only stable counters plus bounded masked evidence. | `RunCheck` remains Python application-layer isolation, not a sealed OS/container boundary; ignored top-level agent/workflow metadata directories are intentionally outside the checked Candidate snapshot. Check code can observe names and metadata exposed by the current Python environment, and Python operations that emit no PEP 578 event, native/kernel bypasses and hostile same-host copy/check races remain possible. Snapshot hashing detects ordinary changes but is not a transactional filesystem snapshot against a hostile concurrent writer. Windows full process-tree termination is not verified. `flock` is advisory and local-filesystem dependent; hostile writers that ignore it and network filesystems with unreliable locking remain outside the guarantee. A lock serializes state commits but cannot prevent two runners from duplicating provider/tool work before one save becomes stale. Plan quality and Evaluator judgement remain model-dependent; confirmation is not proof of completeness, and prompt injection can still affect policy-permitted reasoning. Known-secret/path masking cannot identify every sensitive semantic value. Duo/Triad and every rejection add calls, latency and cost; unavailable usage is reported rather than treated as zero. Default Evaluator still has no command execution unless the host explicitly injects checks. |
| T20 | HTTP controller reuses, widens, races, or leaks a remote-action approval; receipt recovery silently replays an uncertain action | The listener remains loopback-only and requires the existing bearer token. Each process-local `allow_once` approval binds one task ID, normalized MCP scope, canonical arguments digest and 1-3600 second expiry. Task binding is all-or-nothing; consume/revoke use one lock and consumed grants never reopen. The model never sees approval IDs. Durable receipts are prepared before dispatch. HTTP list/resolve requires either a retained task or a durable open receipt with the exact route task ID, remains revision guarded, and cannot call MCP. Public responses and audit omit goal, arguments, evidence text, path, credential and raw exception. | A bearer-token holder remains fully trusted to grant matching MCP actions. Process restart loses unconsumed approvals and requires reissue. A consumed approval with failed receipt persistence is intentionally spent. Receipt confirmation records operator/provider evidence but cannot prove remote business success or exactly-once delivery. |

## External action receipt boundary

Receipt storage at `<project>/.forgeagent/receipts` is host-reserved state.
File tools reject lexical, case-spelled and resolved aliases of this subtree.
Restricted workers reject its accesses and ancestor mutations even after a full-disk
grant; descriptor-relative opens are checked against a resolved directory when the
platform exposes it, and fail closed when provenance is unavailable. Descriptor-targeted
mutations with unknown provenance are denied. Container execution mounts the project's
`.forgeagent` metadata directory read-only, preventing both receipt writes and movement
of its parent binding. Trusted same-process execution retains its explicit no-isolation
contract. Python introspection/native bypasses and a hostile same-user host remain
outside the restricted guarantee.

The private `.catalog` records registered action IDs and `.initialized` distinguishes
an established store from legacy initialization. Missing registered records or a missing
catalog in an initialized store stop execution. Valid legacy records are registered
without changing their bytes or replaying actions. A crash between a new prepared
record and its catalog update can recover only an unregistered `prepared`, revision-0,
open receipt; other unregistered states fail closed. Capacity is checked before creating
a record. Preserve the catalog, marker, and all receipts together in backups; do not
delete them to clear a pending action. Total loss of the directory and all initialization
evidence cannot be distinguished from first use without an independent backup.

Approved non-read-only MCP calls now persist a local, allowed-root receipt through
`prepared` -> `dispatched` -> `confirmed` or `unknown`. `unknown` is not treated as a
normal retryable failure: Loop resume and the next iteration stop with
`external_action_pending` until a caller explicitly confirms, abandons, or authorizes
a new attempt. Listing and reconciliation never dispatch the original action, and a
new attempt must use a new action ID. A confirmed state proves only an MCP protocol
response (or authoritative no-dispatch result), not business-level success or remote
exactly-once execution. Receipt files are bounded, masked, revision-checked and
atomic; malformed/replaced storage fails closed. The audit event is only a bounded
projection and is not the receipt authority. FileWrite, Exec, Edit and WebFetch remain
outside this receipt protocol.

## HTTP action approval boundary

M44 does not turn the HTTP listener into a public remote Gateway: configuration still
rejects non-loopback addresses and provides no TLS, proxy trust, tenant identity or
RBAC. “Remote action” means an external MCP side effect controlled through the local
HTTP plane. Static exact allowlists remain server-owned; dynamic approvals are bounded
process-local capabilities and are checked only after the static allowlist misses.

Approval and receipt state deliberately have different durability. Restart invalidates
every `issued` or `bound` approval, while receipts survive under `allowed_root` so an
uncertain prior dispatch can be reconciled. After restart the matching open receipt,
not a reconstructed task or approval, establishes its exact task-scoped recovery route.
`confirmed`, `abandoned` and
`retry_approved` are CAS state transitions only; none replays MCP, resumes Loop or
creates a replacement action. Custom evidence is stored in the receipt but public and
audit projections reduce it to `provided` rather than exposing its text.

## Bounded file and execution results

FileRead accepts only an opened regular file and reads at most 1 MiB plus one
overflow byte. Oversized files and FIFOs return the fixed FileRead failure;
larger project files can be processed with bounded output through Exec. Skill reads
stop at 256 KiB plus one byte before decoding; native Skills retain their 32 KiB
document limit. Image directory loading stops at the first image beyond twenty.

Each worker stream retains an 8 KiB prefix plus an explicit truncation marker.
The parent continuously drains worker pipes while retaining at most a 1 MiB result
frame and 8 KiB diagnostic stderr. An oversized result, including state, is rejected
without replacing the previous state. Recovery captures use bounded, non-blocking,
no-follow reads and reject non-regular files. These limits bound result retention;
they do not bound arbitrary allocations or disk writes by generated code. Those still
depend on the selected execution tier and its resource limits.

Restricted execution starts in the task project directory. A full-disk grant expands
filesystem authority without changing the working directory used by relative paths.

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
