from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

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

