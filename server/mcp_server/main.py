from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.session_history import history_store
from mcp_server.sdk_bridge import bridge
from mcp_server.tools.build import (
    BuildContext,
    SDK_BRIDGE_PORT,
    build_and_deploy as run_build_and_deploy,
    ensure_adb_reverse_on_startup,
)
from mcp_server.tools.crash import CrashContext, get_crash_context as run_get_crash_context
from mcp_server.tools.fuzz import FuzzContext, start_fuzzing as run_start_fuzzing
from mcp_server.tools.ide import ide_evaluate as run_ide_evaluate
from mcp_server.tools.ide import ide_set_breakpoint as run_ide_set_breakpoint
from mcp_server.tools.network import NetworkContext, inspect_network as run_inspect_network
from mcp_server.tools.report import generate_bug_report as run_generate_bug_report
from mcp_server.tools.state import StateContext, dump_viewmodel as run_dump_viewmodel
from mcp_server.tools.system import DoctorContext, doctor as run_doctor
from mcp_server.tools.ui import (
    ActionType,
    UIFormat,
    UIContext,
    get_ui_tree as run_get_ui_tree,
    interact_and_observe as run_interact_and_observe,
)

DEFAULT_MAX_PAYLOAD_CHARS = 4000
logger = logging.getLogger(__name__)


class ServerRuntime:
    def __init__(self, roots: list[str] | None = None) -> None:
        self.roots = roots or []

    def set_roots(self, roots: list[str]) -> None:
        self.roots = roots

    def get_roots(self) -> list[str]:
        return list(self.roots)

    async def summarize_large_payload(self, payload: str, max_chars: int = DEFAULT_MAX_PAYLOAD_CHARS) -> str:
        """Sampling hook placeholder for payload summarization."""
        if len(payload) <= max_chars:
            return payload
        suffix = "\n...(truncated)..."
        if max_chars <= len(suffix):
            return suffix[:max_chars]
        return payload[: max_chars - len(suffix)] + suffix


runtime = ServerRuntime(roots=[str(Path.cwd())])
mcp = FastMCP("android-deep-debugger")


def _default_ui_context() -> UIContext:
    import uiautomator2 as u2

    device = u2.connect()
    return UIContext(device=device)


@mcp.tool()
def doctor() -> str:
    """Diagnose Android environment with Roots-aware Gradle discovery."""
    return run_doctor(DoctorContext(roots_provider=runtime.get_roots))


@mcp.tool()
async def build_and_deploy(clean: bool = False, variant: str = "debug") -> dict[str, Any]:
    """Build app via Gradle, install APK via adb, and auto-configure adb reverse."""
    result = await run_build_and_deploy(
        context=BuildContext(roots_provider=runtime.get_roots),
        clean=clean,
        variant=variant,
    )
    if "build_log_chunks" in result:
        result["build_log_chunks"] = list(
            await asyncio.gather(
                *[
                    runtime.summarize_large_payload(chunk, max_chars=DEFAULT_MAX_PAYLOAD_CHARS)
                    for chunk in result["build_log_chunks"]
                ]
            )
        )
    return result


@mcp.tool()
def interact_and_observe(
    action: ActionType,
    selector: str,
    value: str | None = None,
) -> dict[str, Any]:
    """Compound UI tool that acts and immediately returns the resulting state."""
    result = run_interact_and_observe(
        context=_default_ui_context(),
        action=action,
        selector=selector,
        value=value,
    )
    history_store.add_action(
        {
            "tool": "interact_and_observe",
            "action": action,
            "selector": selector,
            "value": value,
            "status": "success" if "✅ Success" in result.get("text", "") else "failure",
        }
    )
    return result


@mcp.tool()
def get_ui_tree(format: UIFormat = "summary") -> dict[str, Any]:
    """Retrieve current accessibility tree in summary/json/xml format."""
    return run_get_ui_tree(context=_default_ui_context(), format=format)


@mcp.tool()
def inspect_network(filter: str | None = None) -> dict[str, Any]:
    """Return recent HTTP traffic intercepted by the Agent SDK.

    Requires the Android Agent SDK to be connected via ``adb reverse tcp:8080 tcp:8080``.
    All sensitive fields (Authorization, password, token, credit_card) are automatically
    masked before being returned.
    """
    return run_inspect_network(context=NetworkContext(gateway=bridge), filter=filter)


@mcp.tool()
def dump_viewmodel(class_name: str | None = None) -> dict[str, Any]:
    """Dump the internal StateFlow/LiveData state of active ViewModels from the Agent SDK.

    Requires the Android Agent SDK to be connected via ``adb reverse tcp:8080 tcp:8080``.
    """
    return run_dump_viewmodel(context=StateContext(gateway=bridge), class_name=class_name)


@mcp.tool()
def ide_set_breakpoint(file_path: str, line: int, condition: str | None = None) -> dict[str, Any]:
    """Set breakpoint through IDE bridge (mock bridge in this phase)."""
    return run_ide_set_breakpoint(file_path=file_path, line=line, condition=condition)


@mcp.tool()
def ide_evaluate(expression: str) -> dict[str, Any]:
    """Evaluate expression through IDE bridge (mock bridge in this phase)."""
    return run_ide_evaluate(expression=expression)


@mcp.tool()
def get_crash_context() -> dict[str, Any]:
    """Collect stack trace + recent UI/network/state context when crash/ANR is detected."""
    ui_context = _default_ui_context()
    return run_get_crash_context(
        CrashContext(
            logcat=ui_context.device,
            history=history_store,
            network_gateway=bridge,
            state_gateway=bridge,
        )
    )


@mcp.tool()
def start_fuzzing(duration_sec: int, strategy: str = "random") -> dict[str, Any]:
    """Run autonomous UI fuzzing and stop immediately on crash/ANR."""
    ui_context = _default_ui_context()
    return run_start_fuzzing(
        context=FuzzContext(
            device=ui_context.device,
            crash_context=CrashContext(
                logcat=ui_context.device,
                history=history_store,
                network_gateway=bridge,
                state_gateway=bridge,
            ),
            record_action=history_store.add_action,
        ),
        duration_sec=duration_sec,
        strategy=strategy,  # type: ignore[arg-type]
    )


@mcp.tool()
def generate_bug_report(
    title: str,
    steps: list[str],
    crash_context: dict[str, Any] | None = None,
    logs: list[str] | None = None,
    network_traces: list[dict[str, Any]] | None = None,
    screenshot_base64: str | None = None,
) -> dict[str, Any]:
    """Generate a sanitized Markdown bug report from captured debugging artifacts."""
    return run_generate_bug_report(
        title=title,
        steps=steps,
        crash_context=crash_context,
        logs=logs,
        network_traces=network_traces,
        screenshot_base64=screenshot_base64,
    )


def run() -> None:
    if not ensure_adb_reverse_on_startup():
        logger.warning(
            "adb reverse tcp:%s was not configured on startup (expected if no device is connected); will retry during build_and_deploy.",
            SDK_BRIDGE_PORT,
        )
    mcp.run()


if __name__ == "__main__":
    run()
