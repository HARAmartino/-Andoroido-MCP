"""WebSocket bridge that receives JSON-RPC 2.0 telemetry events from the Android Agent SDK.

The bridge accepts connections from the SDK (tunnelled via ``adb reverse tcp:8080 tcp:8080``),
sanitises every incoming message with :func:`sanitize_log`, then routes it to the
appropriate in-memory store so that :mod:`tools.network` and :mod:`tools.state` can
serve the data to the MCP agent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Masking / sanitization
# ---------------------------------------------------------------------------

_MASK = "***MASKED***"

# String-level regex patterns applied to the *serialised* JSON before parsing.
_STRING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE), r"\1" + _MASK),
    (re.compile(r'"password"\s*:\s*"[^"]*"'), f'"password": "{_MASK}"'),
    (re.compile(r'"token"\s*:\s*"[^"]*"'), f'"token": "{_MASK}"'),
    (re.compile(r'"credit_card"\s*:\s*"[^"]*"'), f'"credit_card": "{_MASK}"'),
]

# Keys whose string values should always be masked when encountered in a parsed dict.
_MASKED_KEYS: frozenset[str] = frozenset({"password", "token", "credit_card"})
_MASKED_HEADER_PREFIXES: tuple[str, ...] = ("authorization",)


def sanitize_log(data: Any) -> Any:  # noqa: ANN401
    """Recursively mask sensitive fields in *data* (dict / list / str).

    This is the canonical sanitizer that *must* be applied to every telemetry
    message before it is stored or returned to the MCP agent.

    Rules (from SPEC §5.2):
    - Authorization header values → ``***MASKED***``
    - ``password``, ``token``, ``credit_card`` string values → ``***MASKED***``
    """
    if isinstance(data, dict):
        return {k: _sanitize_value(k, v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_log(item) for item in data]
    if isinstance(data, str):
        return _apply_string_patterns(data)
    return data


def _sanitize_value(key: str, value: Any) -> Any:  # noqa: ANN401
    lower_key = key.lower()
    if lower_key in _MASKED_KEYS and isinstance(value, str):
        return _MASK
    if any(lower_key.startswith(p) for p in _MASKED_HEADER_PREFIXES) and isinstance(value, str):
        # Mask the entire Authorization header value for maximum safety.
        return _MASK
    return sanitize_log(value)


def _apply_string_patterns(text: str) -> str:
    for pattern, replacement in _STRING_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# In-memory telemetry stores
# ---------------------------------------------------------------------------

MAX_NETWORK_TRACES = 500


@dataclass
class SDKBridge:
    """Holds in-memory telemetry received from the Android Agent SDK.

    Acts as both a *NetworkGateway* and a *StateGateway*; pass ``self`` to
    :class:`tools.network.NetworkContext` and :class:`tools.state.StateContext`.
    """

    _network_traces: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_NETWORK_TRACES)
    )
    _viewmodel_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    _connected: bool = False

    # ------------------------------------------------------------------
    # NetworkGateway protocol
    # ------------------------------------------------------------------

    def get_network_traces(self, filter: str | None = None) -> list[dict[str, Any]]:
        """Return stored network traces, optionally filtered by URL substring or HTTP method."""
        traces: list[dict[str, Any]] = list(self._network_traces)
        if filter:
            f_lower = filter.lower()
            traces = [
                t
                for t in traces
                if f_lower in t.get("request", {}).get("url", "").lower()
                or f_lower == t.get("request", {}).get("method", "").lower()
            ]
        return traces

    # ------------------------------------------------------------------
    # StateGateway protocol
    # ------------------------------------------------------------------

    def get_viewmodel_states(self, class_name: str | None = None) -> dict[str, Any]:
        """Return stored ViewModel states, optionally filtered by class name."""
        if class_name:
            if class_name in self._viewmodel_states:
                return {class_name: self._viewmodel_states[class_name]}
            return {}
        return dict(self._viewmodel_states)

    # ------------------------------------------------------------------
    # SDKGateway protocol (used by UIContext)
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Internal message handling
    # ------------------------------------------------------------------

    def handle_message(self, raw: str) -> None:
        """Parse, sanitise, and route a single JSON-RPC 2.0 message from the SDK."""
        # Apply string-level sanitisation first, then parse.
        sanitised_raw = _apply_string_patterns(raw)
        try:
            msg = json.loads(sanitised_raw)
        except json.JSONDecodeError as exc:
            logger.warning("sdk_bridge: invalid JSON: %s", exc)
            return

        if msg.get("jsonrpc") != "2.0":
            logger.warning("sdk_bridge: not JSON-RPC 2.0, ignoring")
            return

        method = msg.get("method", "")
        params = sanitize_log(msg.get("params", {}))

        if method == "telemetry/network":
            self._network_traces.append(params)
        elif method == "telemetry/state":
            vm_name = params.get("viewmodel", "unknown")
            self._viewmodel_states[vm_name] = params.get("state", {})
        else:
            logger.debug("sdk_bridge: unknown method %r", method)

    # ------------------------------------------------------------------
    # WebSocket server
    # ------------------------------------------------------------------

    async def _handle_ws_client(self, websocket: Any) -> None:  # noqa: ANN401
        self._connected = True
        logger.info("sdk_bridge: SDK client connected")
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    message = message.decode()
                self.handle_message(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sdk_bridge: client error: %s", exc)
        finally:
            self._connected = False
            logger.info("sdk_bridge: SDK client disconnected")

    async def serve(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        """Start the WebSocket server and block until cancelled."""
        import websockets.asyncio.server as ws_server  # type: ignore[import-untyped]

        async with ws_server.serve(self._handle_ws_client, host, port):
            logger.info("sdk_bridge: listening on ws://%s:%d", host, port)
            await asyncio.Future()  # run forever


# ---------------------------------------------------------------------------
# Module-level singleton (used by main.py)
# ---------------------------------------------------------------------------

bridge = SDKBridge()
