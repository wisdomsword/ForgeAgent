"""Compare CodeGraph explore output through CLI and MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from forgeagent.context import ContextConfig, estimate_request_tokens, estimate_text_tokens
from forgeagent.models import Message, Role

DEFAULT_QUERY = "Runtime set_state"
DEFAULT_MAX_FILES = 1
SYSTEM_PROMPT = (
    "You are a coding assistant. Use the provided tool output to answer the user's question."
)


def normalized_text(text: str) -> str:
    return text.removesuffix("\n")


def extract_report_fields(text: str) -> dict[str, int]:
    found = re.search(r"Found (?P<n>\d+) symbols? across (?P<f>\d+) files?", text)
    if found is None:
        raise ValueError("CodeGraph report header not found")

    lines = text.splitlines()
    source_lines = 0
    blast = 0
    not_shown = 0
    section = ""
    for line in lines:
        if line.startswith("**Blast radius"):
            section = "blast"
        elif line.startswith("**Not shown above"):
            section = "not_shown"
        elif line.startswith("**"):
            section = ""
        elif line.startswith("```"):
            section = "source" if section == "" else section
        elif line.startswith("- "):
            if section == "blast":
                blast += 1
            elif section == "not_shown":
                not_shown += 1
        elif section == "source" and re.match(r"^\d+\t", line):
            source_lines += 1
    return {
        "reported_symbols": int(found.group("n")),
        "reported_files": int(found.group("f")),
        "source_line_count": source_lines,
        "blast_radius_entry_count": blast,
        "not_shown_entry_count": not_shown,
    }


def json_metrics(payload: Any, text: str, object_payload: Any | None = None) -> dict[str, int]:
    text_values = [item.get("text", "") for item in payload if item.get("type") == "text"]
    string_json_bytes = sum(
        len(json.dumps(value, ensure_ascii=False).encode("utf-8")) for value in text_values
    )
    content_json = json.dumps(payload, ensure_ascii=False)
    object_json = json.dumps(
        payload if object_payload is None else object_payload, ensure_ascii=False
    )
    return {
        "text_bytes": len(text.encode("utf-8")),
        "text_tokens": estimate_text_tokens(text),
        "string_json_bytes": string_json_bytes,
        "string_escape_bytes": string_json_bytes - len(text.encode("utf-8")),
        "content_json_bytes": len(content_json.encode("utf-8")),
        "content_json_ascii_bytes": len(json.dumps(payload).encode("utf-8")),
        "content_structure_bytes": len(content_json.encode("utf-8")) - string_json_bytes,
        "content_json_tokens": estimate_text_tokens(content_json),
        "object_json_bytes": len(object_json.encode("utf-8")),
        "object_field_bytes": len(object_json.encode("utf-8")) - len(content_json.encode("utf-8")),
        "object_json_tokens": estimate_text_tokens(object_json),
        "object_json_ascii_bytes": len(
            json.dumps(object_payload if object_payload is not None else payload).encode("utf-8")
        ),
    }


def build_context_messages(
    backend: str, path: str, query: str, max_files: int, result: str
) -> list[Message]:
    if backend == "cli":
        invocation = (
            f"Command: codegraph --no-color explore --path {path} --max-files {max_files} '{query}'"
        )
    elif backend == "mcp":
        invocation = (
            f'Tool: codegraph_explore({{"projectPath": "{path}", '
            f'"maxFiles": {max_files}, "query": "{query}"}})'
        )
    else:
        raise ValueError(f"unknown backend: {backend}")
    return [
        Message(role=Role.SYSTEM, content=SYSTEM_PROMPT),
        Message(role=Role.USER, content=f"{invocation}\n\nResult:\n{result}"),
    ]


def result_metrics(
    cli_text: str,
    mcp_text: str,
    path: str = "",
    query: str = DEFAULT_QUERY,
    max_files: int = DEFAULT_MAX_FILES,
) -> dict[str, Any]:
    cli_normalized = normalized_text(cli_text)
    mcp_normalized = mcp_text
    return {
        "cli_text_bytes": len(cli_text.encode("utf-8")),
        "mcp_text_bytes": len(mcp_text.encode("utf-8")),
        "exact_text_equal": cli_text == mcp_text,
        "normalized_text_equal": cli_normalized == mcp_normalized,
        "first_diff_offset": _first_diff_offset(cli_text, mcp_text),
        "cli_t_result_raw": estimate_text_tokens(cli_text),
        "mcp_t_result_raw": estimate_text_tokens(mcp_text),
        "cli_t_result_normalized": estimate_text_tokens(cli_normalized),
        "mcp_t_result_normalized": estimate_text_tokens(mcp_normalized),
        "t_result_normalized": estimate_text_tokens(cli_normalized),
        "cli_t_context": estimate_request_tokens(
            build_context_messages("cli", path, query, max_files, cli_normalized),
            ContextConfig(),
        ),
        "mcp_t_context": estimate_request_tokens(
            build_context_messages("mcp", path, query, max_files, mcp_normalized),
            ContextConfig(),
        ),
        "cli_tail_newline_bytes": int(cli_text.endswith("\n")),
    }


def context_token_metrics(
    cli_text: str,
    mcp_payload: dict[str, Any],
    path: str,
    query: str,
    max_files: int,
) -> dict[str, int]:
    cli_object = json.dumps(
        {"content": [{"type": "text", "text": cli_text}], "isError": False},
        ensure_ascii=False,
    )
    mcp_object = json.dumps(mcp_payload, ensure_ascii=False)
    return {
        "cli_t_context_object": estimate_request_tokens(
            build_context_messages("cli", path, query, max_files, cli_object), ContextConfig()
        ),
        "mcp_t_context_object": estimate_request_tokens(
            build_context_messages("mcp", path, query, max_files, mcp_object), ContextConfig()
        ),
    }


def _first_diff_offset(left: str, right: str) -> int | None:
    for index, (left_char, right_char) in enumerate(zip(left, right, strict=False)):
        if left_char != right_char:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def _run_cli(path: str, query: str, max_files: int) -> str:
    completed = subprocess.run(
        [
            "codegraph",
            "--no-color",
            "explore",
            "--path",
            path,
            "--max-files",
            str(max_files),
            query,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _status(path: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["codegraph", "--no-color", "status", "-j", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _daemon_status() -> str:
    try:
        completed = subprocess.run(
            ["codegraph", "--no-color", "daemon"],
            capture_output=True,
            text=True,
            input="",
            timeout=5,
            check=True,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    except subprocess.CalledProcessError as error:
        return f"exit {error.returncode}: {(error.stdout or error.stderr or '').strip()}"
    return (completed.stdout + completed.stderr).strip()


def _fingerprint(status: dict[str, Any]) -> tuple[Any, ...]:
    pending = status.get("pendingChanges", {})
    return (
        status.get("lastIndexed"),
        status.get("fileCount"),
        status.get("nodeCount"),
        status.get("edgeCount"),
        pending.get("added"),
        pending.get("modified"),
        pending.get("removed"),
    )


async def _run_mcp(
    session: Any, path: str, query: str, max_files: int
) -> tuple[str, dict[str, Any]]:
    result = await session.call_tool(
        "codegraph_explore",
        {"projectPath": path, "maxFiles": max_files, "query": query},
    )
    text = "".join(item.text for item in result.content if item.type == "text")
    return text, result.model_dump(mode="json", by_alias=True, exclude_none=False)


async def run_experiment(
    path: str, query: str, max_files: int, repeats: int, output_dir: Path
) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if max_files <= 0 or repeats <= 0:
        raise ValueError("max_files and repeats must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    parameters = StdioServerParameters(
        command="codegraph",
        args=["serve", "--mcp", "--path", path, "--no-watch"],
    )
    cli_records: list[dict[str, Any]] = []
    mcp_records: list[dict[str, Any]] = []
    status_frames: list[tuple[Any, ...]] = []

    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for index in range(1, repeats + 1):
                current_status = _status(path)
                if index == 1:
                    initial_status = current_status
                    initial_fingerprint = _fingerprint(current_status)
                status_frames.append(_fingerprint(current_status))
                cli_text = _run_cli(path, query, max_files)
                (output_dir / f"cli-{index:02d}.txt").write_text(cli_text, encoding="utf-8")
                mcp_text, mcp_payload = await _run_mcp(session, path, query, max_files)
                (output_dir / f"mcp-{index:02d}.json").write_text(
                    json.dumps(mcp_payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                common = result_metrics(cli_text, mcp_text, path, query, max_files)
                common.update(context_token_metrics(cli_text, mcp_payload, path, query, max_files))
                cli_records.append(
                    {
                        **extract_report_fields(cli_text),
                        **common,
                        "t_wire_payload": estimate_text_tokens(cli_text),
                    }
                )
                mcp_wire = json.dumps(mcp_payload, ensure_ascii=False)
                mcp_records.append(
                    {
                        **extract_report_fields(mcp_text),
                        **json_metrics(mcp_payload["content"], mcp_text, mcp_payload),
                        **common,
                        "t_wire_payload": estimate_text_tokens(mcp_wire),
                    }
                )
            status_frames.append(_fingerprint(_status(path)))

    stable = all(frame == initial_fingerprint for frame in status_frames)
    report = {
        "query": query,
        "path": path,
        "max_files": max_files,
        "repeats": repeats,
        "invocation_count": {"cli": repeats, "mcp": repeats},
        "index_fingerprint_stable": stable,
        "initial_status": initial_status,
        "environment": {
            "codegraph_version": subprocess.run(
                ["codegraph", "--version"], capture_output=True, text=True, check=True
            ).stdout.strip(),
            "mcp_server_args": parameters.args,
            "daemon_status": _daemon_status(),
            "mcp_session": "single session reused for all calls",
        },
        "status_frames": status_frames,
        "cli": _summarize(cli_records),
        "mcp": _summarize(mcp_records),
        "delta": _delta(cli_records[0], mcp_records[0]),
        "provider_token_usage": None,
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    summary: dict[str, Any] = {"runs": records}
    for key, value in records[0].items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values = [record[key] for record in records]
        summary[key] = {"min": min(values), "max": max(values), "median": statistics.median(values)}
    return summary


def _delta(cli: dict[str, Any], mcp: dict[str, Any]) -> dict[str, int]:
    return {
        "text_bytes": mcp["mcp_text_bytes"] - cli["cli_text_bytes"],
        "string_escape_bytes": mcp["string_escape_bytes"],
        "content_structure_bytes": mcp["content_structure_bytes"],
        "object_field_bytes": mcp["object_field_bytes"],
        "cli_tail_newline_bytes": cli["cli_tail_newline_bytes"],
        "object_json_minus_cli_stdout_bytes": mcp["object_json_bytes"] - cli["cli_text_bytes"],
        "t_wire_payload": mcp["t_wire_payload"] - cli["t_wire_payload"],
        "t_context_text_only": mcp["mcp_t_context"] - cli["cli_t_context"],
        "t_context_object": mcp["mcp_t_context_object"] - cli["cli_t_context_object"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="codegraph-parity-"))
    report = asyncio.run(
        run_experiment(args.path, args.query, args.max_files, args.repeats, output_dir)
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "index_fingerprint_stable": report["index_fingerprint_stable"],
                "delta": report["delta"],
                "cli": report["cli"],
                "mcp": report["mcp"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
