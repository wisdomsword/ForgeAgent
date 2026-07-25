# Local HTTP Task Service

ForgeAgent's HTTP entry point is an opt-in, local-only interface for clients that
cannot use the interactive CLI. It is an asynchronous task service, not a remote
multi-tenant API.

## Start and configuration

Start it explicitly with a server-owned YAML file:

```bash
export FORGEAGENT_HTTP_TOKEN='replace-with-a-random-token'
forgeagent serve --config ~/.forgeagent/http.yaml
```

The configuration file owns the bind address, port, model, sandbox tier, allowed
root, audit path, limits, and HTTP allowlist. `FORGEAGENT_HTTP_TOKEN` takes priority
over a `token` value in the file. A missing, blank, non-ASCII, whitespace-containing,
or overlong token fails startup. The token is held in memory and is never written to
responses or audit records. There is no hot reload: change the token or policy and
restart the service.

The listener accepts loopback addresses only (for example, `127.0.0.1` or `::1`; the
configuration uses the platform's `ipaddress` loopback check) and M16 does not provide
TLS. Do not expose the port through a reverse proxy or port forward without
adding an independently reviewed authentication and transport boundary.

Example configuration:

```yaml
token: file-token
bind_host: 127.0.0.1
port: 8765
model: claude-sonnet-5
tier: restricted
allowed_root: /absolute/project/path
audit_path: ~/.forgeagent/http-audit.jsonl
allowlist:
  - mcp/github/create_issue
  - file/write/project.txt
  - web/https/example.com/443/
planner_model: claude-haiku-4-5
evaluator_model: claude-haiku-4-5
evaluator_tier: restricted
max_rejections: 2
triad_plan_policy: deny
allow_weaker_override: false
```

The collaboration settings are also server-owned. Blank role model settings inherit
the service's main model. `evaluator_tier` accepts `restricted` or `container` only;
`max_rejections` is 1-10. `triad_plan_policy: deny` is the safe default: headless
Triad stops with `needs_confirmation` after Planner submission and does not start the
Generator. `preauthorize` approves the bounded submitted plan without a human channel.
`allow_weaker_override` controls whether an explicit task/Duo request may bypass a
deterministic programming-task Triad route. Clients cannot submit any of these fields.

The service uses four workers, a queue of 32, at most 256 retained records, and a
one-hour terminal-result TTL by default. Limits are server-owned. Running tasks are
not evicted to make room for new work. Capacity returns `429` with
`capacity_exceeded`; expired and unknown records return the same non-disclosing `404`
envelope.

### Server-owned context policy

The optional `context` mapping in the server YAML is parsed only by the server. It uses
the same approximate-token sliding-window policy as CLI and REPL: a stable system +
initial-goal prefix and complete assistant + feedback units, with fail-fast behavior
when the prefix or latest complete unit cannot fit. It does not weaken the existing
headless allowlist, confirmation, cancellation, audit, or safe-result boundaries.

`POST /tasks` does not accept context policy, window, feedback limit, or cache options.
The request schema and terminal `usage` projection gain no M17 fields: usage remains
the four raw counts `input_tokens`, `output_tokens`, `cached_tokens`, and
`reasoning_tokens`; cache rate and request-view internals are not exposed over HTTP.

## HTTP contract

Every route requires exactly one `Authorization: Bearer <token>` header. The request
body is JSON with `Content-Type: application/json`, a declared `Content-Length`, and
a 64 KiB default limit. A plain non-empty `goal` remains an ordinary Task unless the
deterministic programming rule selects Triad. Clients may select only the documented
low-risk task/Loop mode fields; unknown fields and all security-sensitive options are
rejected. The server, not the client, chooses `tier`, `backend`, `allowed_root`,
`container_image`, identity/trust, credentials, confirmer, MCP policy, role model,
Evaluator tier, rejection limit, Planner approval and weaker-mode override policy.

| Method | Route | Result |
| --- | --- | --- |
| `POST` | `/tasks` | `202` with `task_id` and initial status |
| `GET` | `/tasks/{32-hex-id}` | `200` bounded lifecycle/result projection |
| `POST` | `/tasks/{32-hex-id}/cancel` | `200` or `202` idempotent cancellation acknowledgement |

Accepted task bodies include:

```json
{"goal": "核对 report.json 的结果", "mode": "duo"}
```

```json
{"goal": "实现 parser.py 并添加测试", "mode": "triad"}
```

New collaborative Loop bodies use the existing endpoint and Loop budgets, with one
additional low-risk frozen field:

```json
{
  "goal": "实现并验证依赖报告生成器",
  "mode": "loop",
  "collaboration_mode": "triad",
  "token_budget": 12000,
  "max_rounds": 20,
  "wall_clock_seconds": 900,
  "max_consecutive_failures": 3
}
```

Loop resume remains `{"mode":"loop","resume_loop_id":"..."}` and cannot include
goal, collaboration mode or budget replacements. No collaboration-specific endpoint
is added; collaboration state paths and IDs are server-owned implementation details.

There is no HTTP shutdown or health-control endpoint. The process owner controls
shutdown and closes the listener, task workers, and shared MCP manager in that order.
The JSON error shape is always `{"error":{"kind":"...","detail":"..."}}`.
It contains stable safe text, never a traceback, bearer token, API key, host path,
prompt, raw tool arguments, or file content.

Terminal ordinary responses expose only `status`, `reason`, a fixed safe `detail`,
bounded `round_count`, aggregate token usage, and `audit_degraded`. Running Duo/Triad
views additionally expose public mode and stable phase. Terminal collaboration views
add plan/pass/fail counts, Generator/Evaluator attempts, rejections,
`usage_available`, normalized usage and bounded masked evidence. They never serialize
the goal, plan/verdict body, prompt, role conversation, raw tool outcome, credential,
artifact content or absolute path.

The Evaluator is read-only at the product tool boundary: its registry contains only
`FileRead`, `FileList`, and `SubmitEvaluation`, and its tier is constrained by the
server. Planner confirmation is separate from the HTTP FileWrite/WebFetch/MCP
allowlist; `triad_plan_policy` cannot be supplied in a request.

Cancellation is cooperative. Queued work is cancelled before constructing a Task;
running work observes the event at the next model-round or tool boundary. It does
not force-kill an in-flight provider request. The registry's one-time terminal
publication makes completion, failure, and cancellation deterministic and leaves
already-terminal results unchanged.

## Allowlist and audit boundary

Headless HTTP confirmation uses exact typed keys only:

* `mcp/<server>/<tool>` for one MCP operation;
* `file/<normalized-project-relative-path>` for one FileWrite target;
* `web/<scheme>/<lowercase-idna-host>/<port>/<normalized-path>` for one WebFetch URL,
  such as `web/https/example.com/443/` for the HTTPS root path.

The HTTP confirmer is the only HTTP pre-approval path. It deliberately does not read
or inherit MCP's CLI/REPL `autoApprove` settings. CLI `autoApprove` compatibility is
kept separate and does not widen HTTP authority. WebFetch checks the initial URL and
every redirect hop against the allowlist.

Audit startup is fail-closed: an unavailable audit path prevents the listener from
starting. Runtime JSONL write/rotation failures are fail-open for task execution,
mark the service degraded, and surface `audit_degraded: true` in subsequent safe
views. Records are secret-masked, rotated with bounded retention, and written with
owner-only (`0600`) permissions where supported. The HTTP lifecycle emits masked
events for authentication failure, reject, capacity, submit, query, and cancel.

## Residual risk

* FileWrite closes its validation/open symlink window with descriptor-relative
  `O_NOFOLLOW` traversal, but cannot roll back writes to an original inode that a
  hostile same-host process concurrently moves or removes.
* Cooperative cancellation cannot interrupt an in-flight provider request.
* Audit startup compaction may read an old log file into memory in one operation.
* The path checks are Unix-oriented and do not claim dedicated Windows UNC coverage.
* If a client disconnects while an error envelope is being written,
  `socketserver` may emit a diagnostic traceback outside the JSON response path.
* Real socket binding and package builds depend on the execution environment; a
  sandbox may deny loopback bind, and packaging may be blocked by DNS. These are
  verification-environment limits, not alternate product behavior.
