from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class MockIDEBridge:
    breakpoints: list[dict[str, Any]]

    def add_breakpoint(self, file_path: str, line: int, condition: str | None = None) -> str:
        breakpoint_id = f"bp-{len(self.breakpoints) + 1}"
        self.breakpoints.append(
            {
                "id": breakpoint_id,
                "file_path": file_path,
                "line": line,
                "condition": condition,
            }
        )
        return breakpoint_id

    def evaluate(self, expression: str) -> str:
        return f"[mock-debugger] Cannot evaluate '{expression}' in mock mode. Connect a real IDE debugger bridge."


_mock_bridge = MockIDEBridge(breakpoints=[])


def ide_set_breakpoint(file_path: str, line: int, condition: str | None = None) -> dict[str, Any]:
    if line <= 0:
        return {
            "status": "error",
            "message": "line must be a positive integer.",
            "mode": "mock",
        }

    breakpoint_id = _mock_bridge.add_breakpoint(file_path=file_path, line=line, condition=condition)
    return {
        "status": "ok",
        "mode": "mock",
        "breakpoint_id": breakpoint_id,
        "text": f"Mock breakpoint set: {file_path}:{line}" + (f" if ({condition})" if condition else ""),
    }


def ide_evaluate(expression: str) -> dict[str, Any]:
    if not expression.strip():
        return {
            "status": "error",
            "message": "expression must not be empty.",
            "mode": "mock",
        }
    return {
        "status": "ok",
        "mode": "mock",
        "expression": expression,
        "value": _mock_bridge.evaluate(expression),
    }
