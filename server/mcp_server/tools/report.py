"""Markdown bug report generation helpers."""
from __future__ import annotations

import json
from typing import Any

from mcp_server.sdk_bridge import sanitize_log


def _json_block(data: Any) -> str:  # noqa: ANN401
    return json.dumps(data, ensure_ascii=False, indent=2)


def generate_bug_report(
    title: str,
    steps: list[str],
    crash_context: dict[str, Any] | None = None,
    logs: list[str] | None = None,
    network_traces: list[dict[str, Any]] | None = None,
    screenshot_base64: str | None = None,
    screenshot_mime: str = "image/png",
) -> dict[str, Any]:
    """Generate a sanitized Markdown bug report from captured crash artifacts."""
    safe_steps = [str(step) for step in steps]
    safe_logs = sanitize_log(logs or [])
    safe_network = sanitize_log(network_traces or [])
    safe_crash_context = sanitize_log(crash_context or {})

    lines: list[str] = [f"# {title}", "", "## Reproduction Steps", ""]
    if safe_steps:
        lines.extend([f"{idx}. {step}" for idx, step in enumerate(safe_steps, start=1)])
    else:
        lines.append("1. (No steps provided)")

    lines.extend(["", "## Crash Context", "```json", _json_block(safe_crash_context), "```"])
    lines.extend(["", "## Log Snippet", "```text", "\n".join(safe_logs), "```"])
    lines.extend(["", "## Network Traces", "```json", _json_block(safe_network), "```"])

    if screenshot_base64:
        lines.extend(
            [
                "",
                "## Screenshot",
                f"![screenshot](data:{screenshot_mime};base64,{screenshot_base64})",
            ]
        )

    markdown = "\n".join(lines).strip()
    return {"title": title, "text": markdown}
