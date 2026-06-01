from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - fallback for local tests without dependency
    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, _name: str) -> None:
            self._tools: list[Any] = []

        def tool(self) -> Any:
            def decorator(func: Any) -> Any:
                self._tools.append(func)
                return func

            return decorator

        def run(self) -> None:
            raise RuntimeError("mcp package is required to run the server")

from mcp_server.tools.system import DoctorContext, doctor as run_doctor
from mcp_server.tools.ui import (
    ActionType,
    UIContext,
    get_ui_tree as run_get_ui_tree,
    interact_and_observe as run_interact_and_observe,
)


@dataclass(slots=True)
class ServerRuntime:
    roots: list[str] = field(default_factory=list)

    def set_roots(self, roots: list[str]) -> None:
        self.roots = roots

    def get_roots(self) -> list[str]:
        return list(self.roots)

    async def summarize_large_payload(self, payload: str, max_chars: int = 4000) -> str:
        """Sampling hook placeholder for payload summarization."""
        if len(payload) <= max_chars:
            return payload
        return payload[: max_chars - 32] + "\n...(truncated in skeleton)..."


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
def get_ui_tree(format: str = "summary") -> dict[str, Any]:
    """Retrieve current accessibility tree in summary/json/xml format."""
    ui_format = format if format in {"summary", "json", "xml"} else "summary"
    return run_get_ui_tree(context=_default_ui_context(), format=ui_format)  # type: ignore[arg-type]


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
