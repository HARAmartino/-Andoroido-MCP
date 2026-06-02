from __future__ import annotations

import random
from dataclasses import dataclass, field

from mcp_server.tools.crash import CrashContext
from mcp_server.tools.fuzz import FuzzContext, start_fuzzing


@dataclass(slots=True)
class MockHistory:
    actions: list[dict] = field(default_factory=list)

    def get_recent_actions(self, limit: int = 5) -> list[dict]:
        return list(self.actions)[-limit:]


@dataclass(slots=True)
class MockFuzzDevice:
    xml: str
    logs_per_iteration: list[list[str]] = field(default_factory=list)
    _iteration: int = 0

    def click(self, selector: str) -> None:
        _ = selector

    def swipe(self, selector: str) -> None:
        _ = selector

    def scroll(self, selector: str) -> None:
        _ = selector

    def dump_hierarchy(self) -> str:
        return self.xml

    def get_recent_logs(self, window_ms: int = 500) -> list[str]:
        _ = window_ms
        idx = min(self._iteration, len(self.logs_per_iteration) - 1)
        logs = self.logs_per_iteration[idx] if self.logs_per_iteration else []
        self._iteration += 1
        return list(logs)


def test_start_fuzzing_stops_immediately_on_crash() -> None:
    current_time = 0.0
    history = MockHistory()
    device = MockFuzzDevice(
        xml='<hierarchy><node resource-id="com.example:id/root"><node resource-id="com.example:id/btn_login"/></node></hierarchy>',
        logs_per_iteration=[
            ["I ActivityManager: safe"],
            ["E AndroidRuntime: FATAL EXCEPTION: main", "java.lang.RuntimeException: crash"],
        ],
    )

    def clock() -> float:
        return current_time

    def sleeper(delay: float) -> None:
        nonlocal current_time
        current_time += delay

    result = start_fuzzing(
        context=FuzzContext(
            device=device,
            crash_context=CrashContext(logcat=device, history=history),
            record_action=history.actions.append,
            random_source=random.Random(0),
            clock=clock,
            sleeper=sleeper,
            step_delay_sec=0.1,
        ),
        duration_sec=3,
        strategy="random",
    )

    assert result["status"] == "stopped_on_crash"
    assert result["fuzzing"]["status"] == "stopped_on_crash"
    assert result["fuzzing"]["iterations"] == 2
    assert result["fuzzing"]["target_selector"] is None
    assert len(history.actions) == 2


def test_start_fuzzing_completes_without_crash() -> None:
    current_time = 0.0
    device = MockFuzzDevice(
        xml='<hierarchy><node resource-id="com.example:id/root"><node text="Login"/></node></hierarchy>',
        logs_per_iteration=[["I ActivityManager: safe"]],
    )

    def clock() -> float:
        return current_time

    def sleeper(delay: float) -> None:
        nonlocal current_time
        current_time += delay

    result = start_fuzzing(
        context=FuzzContext(
            device=device,
            crash_context=CrashContext(logcat=device, history=MockHistory()),
            random_source=random.Random(1),
            clock=clock,
            sleeper=sleeper,
            step_delay_sec=0.5,
        ),
        duration_sec=2,
        strategy="guided",
    )

    assert result["status"] == "completed"
    assert result["strategy"] == "guided"
    assert result["iterations"] > 0


def test_start_fuzzing_clicks_target_selector_before_random_loop() -> None:
    current_time = 0.0
    history = MockHistory()
    device = MockFuzzDevice(
        xml='<hierarchy><node resource-id="com.example:id/root"><node resource-id="com.example:id/btn_crash"/></node></hierarchy>',
        logs_per_iteration=[["E AndroidRuntime: FATAL EXCEPTION: main", "java.lang.NullPointerException: crash"]],
    )

    def clock() -> float:
        return current_time

    def sleeper(delay: float) -> None:
        nonlocal current_time
        current_time += delay

    result = start_fuzzing(
        context=FuzzContext(
            device=device,
            crash_context=CrashContext(logcat=device, history=history),
            record_action=history.actions.append,
            random_source=random.Random(0),
            clock=clock,
            sleeper=sleeper,
        ),
        duration_sec=3,
        strategy="guided",
        target_selector="btn_crash",
    )

    assert result["status"] == "stopped_on_crash"
    assert result["fuzzing"]["target_selector"] == "btn_crash"
    assert result["fuzzing"]["iterations"] == 1
    assert history.actions[0]["selector"] == "btn_crash"
