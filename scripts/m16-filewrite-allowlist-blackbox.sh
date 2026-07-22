#!/usr/bin/env bash

set -u

M16_MODEL=${M16_MODEL:-claude-sonnet-5}
M16_TIMEOUT_SECONDS=${M16_TIMEOUT_SECONDS:-120}
M16_FORGEAGENT_BIN=${M16_FORGEAGENT_BIN:-.venv/bin/forgeagent}
M16_PYTHON_BIN=${M16_PYTHON_BIN:-.venv/bin/python}
TARGET_RELATIVE_PATH=m16-allowlist.txt
TARGET_OPERATION=file/m16-allowlist.txt
TARGET_CONTENT='M16 FileWrite allowlist verified.'
TASK_GOAL='Use exactly one FileWrite tool call to write the exact text "M16 FileWrite allowlist verified." to relative path "m16-allowlist.txt". Do not use Exec, MCP, Python, shell, or any other tool. After the FileWrite result, report completion without another tool call.'

SERVER_PID=
CURRENT_PHASE=
CURRENT_TASK_ID=
CURRENT_AUDIT=
CURRENT_TERMINAL=
CURRENT_SERVER_LOG=

stop_server() {
    if [ -z "${SERVER_PID:-}" ]; then
        return
    fi
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        wait_count=0
        while kill -0 "$SERVER_PID" 2>/dev/null && [ "$wait_count" -lt 50 ]; do
            sleep 0.1
            wait_count=$((wait_count + 1))
        done
        if kill -0 "$SERVER_PID" 2>/dev/null; then
            kill -KILL "$SERVER_PID" 2>/dev/null || true
        fi
    fi
    wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=
}

trap 'stop_server' EXIT
trap 'stop_server; exit 130' INT
trap 'stop_server; exit 143' TERM

if ! case "$M16_TIMEOUT_SECONDS" in
    ''|*[!0-9]*|0) false ;;
    *) true ;;
esac; then
    printf 'FAIL: M16_TIMEOUT_SECONDS must be a positive integer.\n' >&2
    exit 1
fi

if [ -n "${M16_EVIDENCE_DIR:-}" ]; then
    EVIDENCE_DIR=$M16_EVIDENCE_DIR
    mkdir -p "$EVIDENCE_DIR" || exit 1
else
    EVIDENCE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/forgeagent-m16-filewrite.XXXXXX") || exit 1
fi

ALLOWED_ROOT=$EVIDENCE_DIR/allowed-root
EXPECTED_FILE=$EVIDENCE_DIR/expected-content.txt
TARGET_FILE=$ALLOWED_ROOT/$TARGET_RELATIVE_PATH
mkdir -p "$ALLOWED_ROOT" || exit 1
printf '%s' "$TARGET_CONTENT" >"$EXPECTED_FILE" || exit 1

if [ ! -x "$M16_FORGEAGENT_BIN" ]; then
    printf 'Evidence directory: %s\n' "$EVIDENCE_DIR" >&2
    printf 'FAIL: ForgeAgent executable is unavailable: %s\n' "$M16_FORGEAGENT_BIN" >&2
    exit 1
fi
if [ ! -x "$M16_PYTHON_BIN" ]; then
    printf 'Evidence directory: %s\n' "$EVIDENCE_DIR" >&2
    printf 'FAIL: Python executable is unavailable: %s\n' "$M16_PYTHON_BIN" >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    printf 'Evidence directory: %s\n' "$EVIDENCE_DIR" >&2
    printf 'FAIL: curl and jq are required.\n' >&2
    exit 1
fi

BEARER_TOKEN=$(
    "$M16_PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))'
) || exit 1

print_redacted_file() {
    file_path=$1
    if [ ! -f "$file_path" ]; then
        printf '(missing)\n' >&2
        return
    fi
    "$M16_PYTHON_BIN" - "$file_path" "$BEARER_TOKEN" <<'PY' >&2
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
print(text.replace(sys.argv[2], "[REDACTED]"), end="")
if text and not text.endswith("\n"):
    print()
PY
}

print_current_evidence() {
    printf 'Terminal response (%s):\n' "${CURRENT_TERMINAL:-unavailable}" >&2
    if [ -n "${CURRENT_TERMINAL:-}" ]; then
        print_redacted_file "$CURRENT_TERMINAL"
    else
        printf '(unavailable)\n' >&2
    fi
    printf 'Audit evidence for task %s:\n' "${CURRENT_TASK_ID:-unavailable}" >&2
    if [ -n "${CURRENT_AUDIT:-}" ] && [ -f "$CURRENT_AUDIT" ]; then
        "$M16_PYTHON_BIN" - "$CURRENT_AUDIT" "${CURRENT_TASK_ID:-}" "$BEARER_TOKEN" <<'PY' >&2
import json
from pathlib import Path
import sys

audit_path, task_id, token = sys.argv[1:]
matched = False
for line in Path(audit_path).read_text(encoding="utf-8", errors="replace").splitlines():
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if task_id and event.get("task_id") != task_id:
        continue
    print(json.dumps(event, sort_keys=True).replace(token, "[REDACTED]"))
    matched = True
if not matched:
    print("(none)")
PY
    else
        printf '(missing)\n' >&2
    fi
    printf 'Evidence directory: %s\n' "$EVIDENCE_DIR" >&2
}

fail() {
    print_current_evidence
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

inconclusive() {
    print_current_evidence
    printf 'INCONCLUSIVE: %s\n' "$1" >&2
    exit 2
}

find_port() {
    "$M16_PYTHON_BIN" - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", 0))
    print(probe.getsockname()[1])
PY
}

json_string() {
    "$M16_PYTHON_BIN" -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
}

write_config() {
    phase=$1
    port=$2
    allow=$3
    phase_dir=$EVIDENCE_DIR/$phase
    config_path=$phase_dir/config.yaml
    {
        printf 'bind_host: "127.0.0.1"\n'
        printf 'port: %s\n' "$port"
        printf 'model: %s\n' "$(json_string "$M16_MODEL")"
        printf 'tier: "restricted"\n'
        printf 'allowed_root: %s\n' "$(json_string "$ALLOWED_ROOT")"
        printf 'audit_path: %s\n' "$(json_string "$CURRENT_AUDIT")"
        if [ -z "$allow" ]; then
            printf 'allowlist: []\n'
        else
            printf 'allowlist:\n'
            printf '  - %s\n' "$(json_string "$allow")"
        fi
    } >"$config_path" || fail "Could not write $phase configuration."
}

start_server() {
    phase=$1
    allow=$2
    stop_server
    CURRENT_PHASE=$phase
    CURRENT_TASK_ID=
    phase_dir=$EVIDENCE_DIR/$phase
    mkdir -p "$phase_dir" || fail "Could not create evidence for $phase."
    CURRENT_AUDIT=$phase_dir/audit.jsonl
    CURRENT_TERMINAL=$phase_dir/terminal.json
    CURRENT_SERVER_LOG=$phase_dir/server.log
    submit_path=$phase_dir/submit.json
    rm -f "$CURRENT_AUDIT" "$CURRENT_TERMINAL" "$CURRENT_SERVER_LOG" "$submit_path"
    port=$(find_port) || fail "Could not allocate a loopback port for $phase."
    write_config "$phase" "$port" "$allow"

    FORGEAGENT_HTTP_TOKEN=$BEARER_TOKEN \
        "$M16_FORGEAGENT_BIN" serve --config "$phase_dir/config.yaml" \
        >"$CURRENT_SERVER_LOG" 2>&1 &
    SERVER_PID=$!

    readiness_deadline=$((SECONDS + M16_TIMEOUT_SECONDS))
    while [ "$SECONDS" -lt "$readiness_deadline" ]; do
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            printf 'Server log (%s):\n' "$CURRENT_SERVER_LOG" >&2
            print_redacted_file "$CURRENT_SERVER_LOG"
            fail "ForgeAgent server exited before readiness in $phase."
        fi
        readiness_status=$(curl --noproxy '*' --silent --show-error \
            --connect-timeout 1 --max-time 1 \
            --output /dev/null --write-out '%{http_code}' \
            --header "Authorization: Bearer $BEARER_TOKEN" \
            "http://127.0.0.1:$port/__m16_readiness__" 2>/dev/null || true)
        if [ "$readiness_status" = 404 ]; then
            CURRENT_PORT=$port
            return
        fi
        sleep 0.1
    done
    printf 'Server log (%s):\n' "$CURRENT_SERVER_LOG" >&2
    print_redacted_file "$CURRENT_SERVER_LOG"
    fail "ForgeAgent server did not become ready in $phase."
}

submit_task() {
    submit_path=$EVIDENCE_DIR/$CURRENT_PHASE/submit.json
    request_body=$(jq -cn --arg goal "$TASK_GOAL" '{goal:$goal}') || fail "Could not encode task."
    response_status=$(curl --noproxy '*' --silent --show-error \
        --connect-timeout 2 --max-time "$M16_TIMEOUT_SECONDS" \
        --output "$submit_path" --write-out '%{http_code}' \
        --header "Authorization: Bearer $BEARER_TOKEN" \
        --header 'Content-Type: application/json' \
        --data "$request_body" \
        "http://127.0.0.1:$CURRENT_PORT/tasks") || fail "Task submission failed."
    if [ "$response_status" != 202 ]; then
        CURRENT_TERMINAL=$submit_path
        fail "POST /tasks returned HTTP $response_status instead of 202."
    fi
    CURRENT_TASK_ID=$(jq -er '.task_id | select(type == "string")' "$submit_path") \
        || fail "POST /tasks did not return a task id."
}

poll_terminal() {
    poll_deadline=$((SECONDS + M16_TIMEOUT_SECONDS))
    while [ "$SECONDS" -lt "$poll_deadline" ]; do
        response_status=$(curl --noproxy '*' --silent --show-error \
            --connect-timeout 2 --max-time 2 \
            --output "$CURRENT_TERMINAL" --write-out '%{http_code}' \
            --header "Authorization: Bearer $BEARER_TOKEN" \
            "http://127.0.0.1:$CURRENT_PORT/tasks/$CURRENT_TASK_ID") \
            || fail "Task status query failed."
        if [ "$response_status" != 200 ]; then
            fail "GET /tasks/{id} returned HTTP $response_status instead of 200."
        fi
        status=$(jq -er '.status | select(type == "string")' "$CURRENT_TERMINAL") \
            || fail "Task status response is invalid."
        case "$status" in
            queued|running)
                sleep 0.2
                ;;
            *)
                return
                ;;
        esac
    done
    fail "Task $CURRENT_TASK_ID did not reach a terminal state within $M16_TIMEOUT_SECONDS seconds."
}

has_decision() {
    decision=$1
    [ -f "$CURRENT_AUDIT" ] && jq -s -e \
        --arg task "$CURRENT_TASK_ID" \
        --arg decision "$decision" \
        'any(.[]; .task_id == $task
            and .event_type == "confirmation.decision"
            and .parameters.operation == "file/m16-allowlist.txt"
            and .result_status == $decision)' \
        "$CURRENT_AUDIT" >/dev/null 2>&1
}

current_task_tool_operation_count() {
    if [ ! -f "$CURRENT_AUDIT" ]; then
        printf '0\n'
        return
    fi
    jq -s -r \
        --arg task "$CURRENT_TASK_ID" \
        '[.[] | select(.task_id == $task and .event_type == "tool.operation")] | length' \
        "$CURRENT_AUDIT"
}

has_target_filewrite_operation() {
    [ -f "$CURRENT_AUDIT" ] && jq -s -e \
        --arg task "$CURRENT_TASK_ID" \
        '. as $events
        | [$events[] | select(
            .task_id == $task
            and .event_type == "confirmation.decision"
            and .parameters.operation == "file/m16-allowlist.txt"
          )] as $decisions
        | any($decisions[];
            .operation_id as $operation
            | any($events[];
                .task_id == $task
                and .event_type == "tool.operation"
                and .operation_id == $operation
                and .parameters.tool == "FileWrite"
              )
          )' \
        "$CURRENT_AUDIT" >/dev/null 2>&1
}

has_matching_tool_result() {
    decision=$1
    tool_status=$2
    [ -f "$CURRENT_AUDIT" ] && jq -s -e \
        --arg task "$CURRENT_TASK_ID" \
        --arg decision "$decision" \
        --arg tool_status "$tool_status" \
        '. as $events
        | [$events[] | select(
            .task_id == $task
            and .event_type == "confirmation.decision"
            and .parameters.operation == "file/m16-allowlist.txt"
            and .result_status == $decision
          )] as $decisions
        | any($decisions[];
            .operation_id as $operation
            | any($events[];
                .task_id == $task
                and .event_type == "tool.operation"
                and .operation_id == $operation
                and .parameters.tool == "FileWrite"
                and .result_status == $tool_status
              )
          )' \
        "$CURRENT_AUDIT" >/dev/null 2>&1
}

require_only_target_filewrite() {
    tool_count=$(current_task_tool_operation_count) \
        || fail "Could not inspect current-task tool operations."
    if [ "$tool_count" -gt 1 ]; then
        inconclusive "The model emitted additional tool operations."
    fi
    if [ "$tool_count" -eq 1 ] && ! has_target_filewrite_operation; then
        inconclusive "The model emitted a different tool operation."
    fi
}

audit_contains_bearer_token() {
    [ -f "$CURRENT_AUDIT" ] && grep -Fq -- "$BEARER_TOKEN" "$CURRENT_AUDIT"
}

allowed_root_has_artifact() {
    find "$ALLOWED_ROOT" -mindepth 1 -print -quit 2>/dev/null | grep -q .
}

run_denied_phase() {
    rm -f "$TARGET_FILE"
    start_server denied ''
    submit_task
    poll_terminal
    require_only_target_filewrite
    if has_decision preapproved; then
        fail "Empty allowlist preapproved the target FileWrite."
    fi
    if ! has_decision denied; then
        if allowed_root_has_artifact; then
            inconclusive "The model used an alternative write path in the denied phase."
        fi
        inconclusive "The model did not call the target FileWrite in the denied phase."
    fi
    if ! has_matching_tool_result denied failed; then
        fail "Denied FileWrite has no operation-linked failed tool result."
    fi
    if [ -e "$TARGET_FILE" ] || allowed_root_has_artifact; then
        inconclusive "The model produced an alternative filesystem write in the denied phase."
    fi
    if audit_contains_bearer_token; then
        fail "Bearer token appeared in the audit log."
    fi
    DENIED_TASK_ID=$CURRENT_TASK_ID
    printf 'PASS: empty allowlist denied FileWrite (task %s)\n' "$DENIED_TASK_ID"
    stop_server
}

run_allowed_phase() {
    rm -f "$TARGET_FILE"
    start_server allowed "$TARGET_OPERATION"
    submit_task
    poll_terminal
    require_only_target_filewrite
    if has_decision denied; then
        fail "Exact allowlist denied the target FileWrite."
    fi
    if ! has_decision preapproved; then
        inconclusive "The model did not call the target FileWrite in the allowed phase."
    fi
    if ! has_matching_tool_result preapproved success; then
        fail "Preapproved FileWrite has no operation-linked successful tool result."
    fi
    if [ ! -f "$TARGET_FILE" ]; then
        fail "Successful FileWrite did not create the target file."
    fi
    if ! cmp -s "$EXPECTED_FILE" "$TARGET_FILE"; then
        fail "Target file content does not match the fixed expected content."
    fi
    audit_mode=$(
        "$M16_PYTHON_BIN" -c \
            'import os, stat, sys; print(f"{stat.S_IMODE(os.stat(sys.argv[1]).st_mode):04o}")' \
            "$CURRENT_AUDIT"
    ) || fail "Could not inspect audit permissions."
    if [ "$audit_mode" != 0600 ]; then
        fail "Audit file mode is $audit_mode instead of 0600."
    fi
    if audit_contains_bearer_token; then
        fail "Bearer token appeared in the audit log."
    fi
    ALLOWED_TASK_ID=$CURRENT_TASK_ID
    printf 'PASS: exact allowlist preapproved FileWrite (task %s)\n' "$ALLOWED_TASK_ID"
    stop_server
}

run_denied_phase
run_allowed_phase
printf 'PASS: M16 FileWrite allowlist blackbox contract verified.\n'
printf 'Evidence directory: %s\n' "$EVIDENCE_DIR"
