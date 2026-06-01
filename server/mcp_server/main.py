from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.tools.system import DoctorContext, doctor as run_doctor
from mcp_server.tools.ui import (
    ActionType,
    UIFormat,
    UIContext,
    get_ui_tree as run_get_ui_tree,
    interact_and_observe as run_interact_and_observe,
)

DEFAULT_MAX_PAYLOAD_CHARS = 4000


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
def interact_and_observe(
    action: ActionType,
    selector: str,
    value: str | None = None,
) -> dict[str, Any]:
    """Compound UI tool that acts and immediately returns the resulting state."""
    return run_interact_and_observe(
        context=_default_ui_context(),
        action=action,
        selector=selector,
        value=value,
    )


@mcp.tool()
def get_ui_tree(format: UIFormat = "summary") -> dict[str, Any]:
    """Retrieve current accessibility tree in summary/json/xml format."""
    return run_get_ui_tree(context=_default_ui_context(), format=format)


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
