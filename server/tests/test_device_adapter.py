"""Unit tests for UiAutomator2Adapter (no real device required).

A lightweight fake mimics the parts of the uiautomator2 API the adapter uses,
verifying selector translation and action dispatch without touching hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mcp_server.device import ElementNotFound, UiAutomator2Adapter


@dataclass
class FakeScroll:
    vert_forward_calls: int = 0

    @property
    def vert(self) -> "FakeScroll":
        return self

    def forward(self) -> None:
        self.vert_forward_calls += 1


@dataclass
class FakeElement:
    exists: bool = False
    clicked: int = 0
    long_clicked: int = 0
    set_text_value: str | None = None
    swipe_dirs: list[str] = field(default_factory=list)
    scroll: FakeScroll = field(default_factory=FakeScroll)

    def click(self) -> None:
        self.clicked += 1

    def long_click(self) -> None:
        self.long_clicked += 1

    def set_text(self, value: str) -> None:
        self.set_text_value = value

    def swipe(self, direction: str) -> None:
        self.swipe_dirs.append(direction)


@dataclass
class FakeDevice:
    """Mimics uiautomator2.Device call patterns used by the adapter."""

    serial: str = "FAKESERIAL"
    # Map of (kwarg_name, value) -> FakeElement to return.
    elements: dict[tuple[str, str], FakeElement] = field(default_factory=dict)
    queries: list[dict] = field(default_factory=list)
    coord_clicks: list[tuple[int, int]] = field(default_factory=list)
    coord_long_clicks: list[tuple[int, int]] = field(default_factory=list)

    def click(self, x: int, y: int) -> None:
        self.coord_clicks.append((x, y))

    def long_click(self, x: int, y: int) -> None:
        self.coord_long_clicks.append((x, y))

    def __call__(self, **kwargs) -> FakeElement:
        self.queries.append(kwargs)
        # Single-kwarg selector queries, matching the adapter's strategies.
        for key, val in kwargs.items():
            el = self.elements.get((key, val))
            if el is not None:
                return el
        return FakeElement(exists=False)

    def dump_hierarchy(self) -> str:
        return "<hierarchy><node/></hierarchy>"


@pytest.fixture
def device() -> FakeDevice:
    return FakeDevice()


def test_resolve_by_exact_resource_id(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    device.elements[("resourceId", "com.example:id/btn")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.click("com.example:id/btn")
    assert el.clicked == 1


def test_resolve_by_resource_id_suffix(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    # Adapter uses resourceIdMatches with a regex anchored to the suffix.
    device.elements[("resourceIdMatches", r".*[:/]btn_login$")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.click("btn_login")
    assert el.clicked == 1


def test_resolve_by_text(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    device.elements[("text", "Login")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.long_click("Login")
    assert el.long_clicked == 1


def test_resolve_by_description(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    device.elements[("description", "Submit button")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.click("Submit button")
    assert el.clicked == 1


def test_input_text_focuses_then_sets(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    device.elements[("resourceId", "field")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.input_text("field", "hello@example.com")
    assert el.clicked == 1  # focused first
    assert el.set_text_value == "hello@example.com"


def test_swipe_uses_up_direction(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    device.elements[("text", "list")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.swipe("list")
    assert el.swipe_dirs == ["up"]


def test_scroll_prefers_scroll_gesture(device: FakeDevice) -> None:
    el = FakeElement(exists=True)
    device.elements[("resourceId", "scrollable")] = el
    adapter = UiAutomator2Adapter(device)
    adapter.scroll("scrollable")
    assert el.scroll.vert_forward_calls == 1
    assert el.swipe_dirs == []  # did not fall back to swipe


def test_click_coordinate_handle_bypasses_selector_resolution(device: FakeDevice) -> None:
    adapter = UiAutomator2Adapter(device)
    adapter.click("@60,50")
    assert device.coord_clicks == [(60, 50)]
    assert device.queries == []  # no selector lookup attempted


def test_long_click_coordinate_handle(device: FakeDevice) -> None:
    adapter = UiAutomator2Adapter(device)
    adapter.long_click("@12,34")
    assert device.coord_long_clicks == [(12, 34)]


def test_missing_element_raises_runtime_error(device: FakeDevice) -> None:
    adapter = UiAutomator2Adapter(device)
    with pytest.raises(ElementNotFound):
        adapter.click("nonexistent")
    # ElementNotFound is a RuntimeError subclass, matching the protocol contract
    # that tools.ui / tools.fuzz catch (they expect RuntimeError on failure).
    assert issubclass(ElementNotFound, RuntimeError)


def test_dump_hierarchy_delegates(device: FakeDevice) -> None:
    adapter = UiAutomator2Adapter(device)
    assert adapter.dump_hierarchy() == "<hierarchy><node/></hierarchy>"


def test_get_recent_logs_parses_lines(monkeypatch: pytest.MonkeyPatch, device: FakeDevice) -> None:
    captured_cmd: list[str] = []

    class _Result:
        stdout = "line1\nline2\nline3"

    def fake_run(cmd, **_kwargs):
        captured_cmd.extend(cmd)
        return _Result()

    monkeypatch.setattr("mcp_server.device.subprocess.run", fake_run)
    adapter = UiAutomator2Adapter(device, serial="FAKESERIAL")
    logs = adapter.get_recent_logs(window_ms=500)
    assert logs == ["line1", "line2", "line3"]
    # Serial must be threaded into the adb invocation.
    assert "-s" in captured_cmd and "FAKESERIAL" in captured_cmd
    assert "logcat" in captured_cmd


def test_get_recent_logs_handles_adb_failure(monkeypatch: pytest.MonkeyPatch, device: FakeDevice) -> None:
    def fake_run(cmd, **_kwargs):
        raise FileNotFoundError("adb not found")

    monkeypatch.setattr("mcp_server.device.subprocess.run", fake_run)
    adapter = UiAutomator2Adapter(device)
    assert adapter.get_recent_logs() == []
