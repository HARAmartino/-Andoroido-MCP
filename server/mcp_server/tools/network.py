"""``inspect_network`` MCP tool – surfaces recent HTTP traffic from the Agent SDK."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class NetworkGateway(Protocol):
    """Protocol implemented by :class:`mcp_server.sdk_bridge.SDKBridge`."""

    def get_network_traces(self, filter: str | None = None) -> list[dict[str, Any]]: ...

    def is_connected(self) -> bool: ...


@dataclass(slots=True)
class NetworkContext:
    gateway: NetworkGateway


def inspect_network(
    context: NetworkContext,
    filter: str | None = None,
) -> dict[str, Any]:
    """Return recent HTTP traffic captured by the Agent SDK OkHttp interceptor.

    Args:
        context: Holds the gateway that provides network trace data.
        filter: Optional substring matched against the request URL, or an HTTP
                method name (case-insensitive, e.g. ``"POST"`` or
                ``"api.example.com"``).

    Returns:
        A dict with ``"traces"`` (list of sanitised :class:`NetworkTrace` dicts)
        and ``"sdk_connected"`` (bool).  When the SDK is not connected the list
        is empty and ``"warning"`` is set.
    """
    if not context.gateway.is_connected():
        return {
            "sdk_connected": False,
            "warning": "SDK not connected (error 5001 SDKNotConnected). Start the app and verify `adb reverse tcp:8080 tcp:8080`.",
            "traces": [],
        }

    traces = context.gateway.get_network_traces(filter=filter)
    return {
        "sdk_connected": True,
        "filter": filter,
        "count": len(traces),
        "traces": traces,
    }
