"""``dump_viewmodel`` MCP tool – exposes ViewModel StateFlow/LiveData values from the Agent SDK."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class StateGateway(Protocol):
    """Protocol implemented by :class:`mcp_server.sdk_bridge.SDKBridge`."""

    def get_viewmodel_states(self, class_name: str | None = None) -> dict[str, Any]: ...

    def is_connected(self) -> bool: ...


@dataclass(slots=True)
class StateContext:
    gateway: StateGateway


def dump_viewmodel(
    context: StateContext,
    class_name: str | None = None,
) -> dict[str, Any]:
    """Return the current internal state of active ViewModels captured by the Agent SDK.

    Args:
        context: Holds the gateway that provides ViewModel state data.
        class_name: Optional exact ViewModel class name to filter by
                    (e.g. ``"LoginViewModel"``).  When omitted, all known
                    ViewModel states are returned.

    Returns:
        A dict with ``"states"`` (mapping of class name → state dict) and
        ``"sdk_connected"`` (bool).  When the SDK is not connected, ``"warning"``
        is set.
    """
    if not context.gateway.is_connected():
        return {
            "sdk_connected": False,
            "warning": "SDK not connected (error 5001 SDKNotConnected). Start the app and verify `adb reverse tcp:8080 tcp:8080`.",
            "states": {},
        }

    states = context.gateway.get_viewmodel_states(class_name=class_name)
    result: dict[str, Any] = {
        "sdk_connected": True,
        "class_name_filter": class_name,
        "count": len(states),
        "states": states,
    }
    if class_name and not states:
        result["warning"] = f"No state found for ViewModel '{class_name}'."
    return result
