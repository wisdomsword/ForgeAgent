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

The listener accepts loopback addresses only (`127.0.0.1` or `::1`) and M16 does not
provide TLS. Do not expose the port through a reverse proxy or port forward without
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
  - web/example.com
```

The service uses four workers, a queue of 32, at most 256 retained records, and a
one-hour terminal-result TTL by default. Limits are server-owned. Running tasks are
not evicted to make room for new work. Capacity returns `429` with
`capacity_exceeded`; expired and unknown records return the same non-disclosing `404`
envelope.

## HTTP contract

Every route requires exactly one `Authorization: Bearer <token>` header. The request
body is JSON with `Content-Type: application/json`, a declared `Content-Length`, and
a 64 KiB default limit. `POST /tasks` accepts only a non-empty string `goal`; unknown
fields and all security-sensitive options are rejected. The server, not the client,
chooses `tier`, `backend`, `allowed_root`, `container_image`, identity/trust,
credentials, confirmer, and MCP policy.

| Method | Route | Result |
| --- | --- | --- |
| `POST` | `/tasks` | `202` with `task_id` and initial status |
| `GET` | `/tasks/{32-hex-id}` | `200` bounded lifecycle/result projection |
| `POST` | `/tasks/{32-hex-id}/cancel` | `200` or `202` idempotent cancellation acknowledgement |

There is no HTTP shutdown or health-control endpoint. The process owner controls
shutdown and closes the listener, task workers, and shared MCP manager in that order.
The JSON error shape is always `{"error":{"kind":"...","detail":"..."}}`.
It contains stable safe text, never a traceback, bearer token, API key, host path,
prompt, raw tool arguments, or file content.

Terminal responses expose only `status`, `reason`, a fixed safe `detail`, bounded
`round_count`, aggregate token usage, and `audit_degraded`. Model prose and tool
outcomes are retained only inside the process/audit policy and are not serialized by
the HTTP projection.

Cancellation is cooperative. Queued work is cancelled before constructing a Task;
running work observes the event at the next model-round or tool boundary. It does
not force-kill an in-flight provider request. The registry's one-time terminal
publication makes completion, failure, and cancellation deterministic and leaves
already-terminal results unchanged.

## Allowlist and audit boundary

Headless HTTP confirmation uses exact typed keys only:

* `mcp/<server>/<tool>` for one MCP operation;
* `file/<normalized-project-relative-path>` for one FileWrite target;
* `web/<lowercase-idna-host>` for one WebFetch host.

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

* FileWrite canonical path validation and pathname open still have a hostile-host
  symlink TOCTOU window.
* Cooperative cancellation cannot interrupt an in-flight provider request.
* Audit startup compaction may read an old log file into memory in one operation.
* The path checks are Unix-oriented and do not claim dedicated Windows UNC coverage.
* If a client disconnects while an error envelope is being written,
  `socketserver` may emit a diagnostic traceback outside the JSON response path.
* Real socket binding and package builds depend on the execution environment; a
  sandbox may deny loopback bind, and packaging may be blocked by DNS. These are
  verification-environment limits, not alternate product behavior.
