from __future__ import annotations

from dataclasses import dataclass, field

from mcp_server.tools.crash import CrashContext, get_crash_context
from tests.conftest import MockNetworkGateway, MockStateGateway


@dataclass(slots=True)
class MockLogcat:
    logs: list[str] = field(default_factory=list)

    def get_recent_logs(self, window_ms: int = 500) -> list[str]:
        _ = window_ms
        return list(self.logs)


@dataclass(slots=True)
class MockHistory:
    actions: list[dict] = field(default_factory=list)

    def get_recent_actions(self, limit: int = 5) -> list[dict]:
        return list(self.actions)[-limit:]


def test_get_crash_context_aggregates_recent_artifacts() -> None:
    logcat = MockLogcat(
        logs=[
            "I ActivityManager: Start proc",
            "E AndroidRuntime: FATAL EXCEPTION: main",
            "java.lang.NullPointerException: Boom",
            "\tat com.example.MainActivity.onCreate(MainActivity.kt:42)",
        ]
    )
    history = MockHistory(actions=[{"tool": "interact_and_observe", "step": i} for i in range(7)])
    network = MockNetworkGateway(
        connected=True,
        traces=[{"request": {"url": f"https://api.example.com/{i}"}, "response": {}} for i in range(8)],
    )
    state = MockStateGateway(connected=True, states={"LoginViewModel": {"isLoading": False}})

    result = get_crash_context(
        CrashContext(
            logcat=logcat,
            history=history,
            network_gateway=network,
            state_gateway=state,
        )
    )

    assert result["status"] == "crash_detected"
    assert result["crash_detected"] is True
    assert len(result["ui_actions"]) == 5
    assert result["ui_actions"][0]["step"] == 2
    assert len(result["network_traces"]) == 5
    assert result["network_traces"][0]["request"]["url"].endswith("/3")
    assert "LoginViewModel" in result["viewmodel_state"]
    assert "## Crash Context" in result["text"]


def test_get_crash_context_no_crash_detected() -> None:
    result = get_crash_context(
        CrashContext(
            logcat=MockLogcat(logs=["I ActivityManager: all good"]),
            history=MockHistory(actions=[]),
            network_gateway=MockNetworkGateway(connected=False),
            state_gateway=MockStateGateway(connected=False),
        )
    )

    assert result["status"] == "no_crash_detected"
    assert result["crash_detected"] is False
    assert result["stack_trace"] == []

