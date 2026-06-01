"""Crash context aggregation helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from mcp_server.sdk_bridge import sanitize_log

CRASH_MARKERS: tuple[str, ...] = ("FATAL EXCEPTION", " ANR in ")
STACK_TRACE_LIMIT = 40


class LogcatProvider(Protocol):
    def get_recent_logs(self, window_ms: int = 500) -> list[str]: ...


class HistoryProvider(Protocol):
    def get_recent_actions(self, limit: int = 5) -> list[dict[str, Any]]: ...


class NetworkGateway(Protocol):
    def get_network_traces(self, filter: str | None = None) -> list[dict[str, Any]]: ...

    def is_connected(self) -> bool: ...


class StateGateway(Protocol):
    def get_viewmodel_states(self, class_name: str | None = None) -> dict[str, Any]: ...

    def is_connected(self) -> bool: ...


@dataclass(slots=True)
class CrashContext:
    logcat: LogcatProvider
    history: HistoryProvider
    network_gateway: NetworkGateway | None = None
    state_gateway: StateGateway | None = None
    log_window_ms: int = 2000


def contains_crash_signature(log_lines: list[str]) -> bool:
    return any(any(marker in line for marker in CRASH_MARKERS) for line in log_lines)


def _find_last_crash_index(log_lines: list[str]) -> int | None:
    for idx in range(len(log_lines) - 1, -1, -1):
        if any(marker in log_lines[idx] for marker in CRASH_MARKERS):
            return idx
    return None


def _extract_stack_trace(log_lines: list[str], start_idx: int) -> list[str]:
    stack: list[str] = []
    for line in log_lines[start_idx : start_idx + STACK_TRACE_LIMIT]:
        stripped = line.strip()
        if not stripped:
            break
        if line.startswith("---------"):
            break
        stack.append(line)
    return stack


def _json_block(value: Any) -> str:  # noqa: ANN401
    return json.dumps(sanitize_log(value), ensure_ascii=False, indent=2)


def get_crash_context(
    context: CrashContext,
    log_lines: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate stack trace + recent action/network/state context around a crash."""
    logs = log_lines if log_lines is not None else context.logcat.get_recent_logs(window_ms=context.log_window_ms)
    crash_index = _find_last_crash_index(logs)
    stack_lines = _extract_stack_trace(logs, crash_index) if crash_index is not None else []

    ui_actions = context.history.get_recent_actions(limit=5)

    network_traces: list[dict[str, Any]] = []
    if context.network_gateway and context.network_gateway.is_connected():
        network_traces = context.network_gateway.get_network_traces()[-5:]

    viewmodel_state: dict[str, Any] = {}
    if context.state_gateway and context.state_gateway.is_connected():
        viewmodel_state = context.state_gateway.get_viewmodel_states()

    stack_text = "\n".join(stack_lines) if stack_lines else "No crash or ANR signature found in recent logcat window."

    report = "\n".join(
        [
            "## Crash Context",
            "",
            f"- **Crash Detected**: {'Yes' if crash_index is not None else 'No'}",
            f"- **Log Window (ms)**: {context.log_window_ms}",
            "",
            "### Stack Trace",
            "```text",
            stack_text,
            "```",
            "",
            "### Last 5 UI Actions (`session://history`)",
            "```json",
            _json_block(ui_actions),
            "```",
            "",
            "### Last 5 Network Traces",
            "```json",
            _json_block(network_traces),
            "```",
            "",
            "### Current ViewModel State",
            "```json",
            _json_block(viewmodel_state),
            "```",
        ]
    )

    return {
        "status": "crash_detected" if crash_index is not None else "no_crash_detected",
        "crash_detected": crash_index is not None,
        "stack_trace": stack_lines,
        "ui_actions": ui_actions,
        "network_traces": network_traces,
        "viewmodel_state": viewmodel_state,
        "text": sanitize_log(report),
    }

