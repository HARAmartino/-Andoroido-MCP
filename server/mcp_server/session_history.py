from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

# SPEC-aligned bounded in-memory session history to prevent unbounded growth.
# When full, deque(maxlen=...) automatically drops the oldest entries first.
# 500 keeps enough interaction context for crash triage while remaining lightweight.
MAX_HISTORY = 500


@dataclass(slots=True)
class SessionHistoryStore:
    _actions: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_HISTORY))

    def add_action(self, action: dict[str, Any]) -> None:
        self._actions.append(dict(action))

    def get_recent_actions(self, limit: int = 5) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self._actions)[-limit:]

    def clear(self) -> None:
        self._actions.clear()


history_store = SessionHistoryStore()
