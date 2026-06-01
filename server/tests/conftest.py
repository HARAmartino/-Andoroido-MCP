from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mcp_server.tools.system import DoctorContext
from mcp_server.tools.ui import UIContext


@dataclass(slots=True)
class MockAdb:
    responses: dict[tuple[str, ...], str] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, *args: str) -> str:
        key = tuple(args)
        self.calls.append(key)
        if key not in self.responses:
            raise RuntimeError(f"Unexpected adb command: {key}")
        return self.responses[key]


@dataclass(slots=True)
class MockSDKGateway:
    connected: bool = True

    def is_connected(self) -> bool:
        return self.connected


@dataclass(slots=True)
class MockDevice:
    current_xml: str
    logs: list[str] = field(default_factory=list)

    def click(self, selector: str) -> None:
        self._require(selector)
        self.current_xml = self.current_xml.replace('text="Login"', 'text="Login successful"')
        self.logs.append("I ActivityManager: click(Login)")

    def long_click(self, selector: str) -> None:
        self._require(selector)
        self.logs.append("I ActivityManager: long_click")

    def input_text(self, selector: str, value: str) -> None:
        self._require(selector)
        self.current_xml = self.current_xml.replace('text=""', f'text="{value}"')
        self.logs.append(f"I InputMethod: set_text({selector})")

    def swipe(self, selector: str) -> None:
        self._require(selector)
        self.logs.append("I ViewRootImpl: swipe")

    def scroll(self, selector: str) -> None:
        self._require(selector)
        self.logs.append("I ViewRootImpl: scroll")

    def dump_hierarchy(self) -> str:
        return self.current_xml

    def get_recent_logs(self, window_ms: int = 500) -> list[str]:
        del window_ms
        return list(self.logs)

    def _require(self, selector: str) -> None:
        if selector not in self.current_xml:
            raise ValueError(f"ElementNotFound: {selector}")


@pytest.fixture
def sample_ui_xml() -> str:
    return (
        '<hierarchy><node resource-id="com.example:id/root" text="">'
        '<node resource-id="com.example:id/btn_login" text="Login" />'
        '<node resource-id="com.example:id/input_email" text="" />'
        "</node></hierarchy>"
    )


@pytest.fixture
def mock_device(sample_ui_xml: str) -> MockDevice:
    return MockDevice(current_xml=sample_ui_xml)


@pytest.fixture
def ui_context(mock_device: MockDevice) -> UIContext:
    return UIContext(device=mock_device, sdk_gateway=MockSDKGateway())


@pytest.fixture
def doctor_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DoctorContext:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "gradlew").write_text("#!/bin/sh\n")

    adb = MockAdb(
        responses={
            ("version",): "Android Debug Bridge version 1.0.41",
            ("devices",): "List of devices attached\nemulator-5554\tdevice",
            ("-s", "emulator-5554", "shell", "getprop", "ro.build.version.release"): "15",
            ("-s", "emulator-5554", "shell", "getprop", "ro.build.version.sdk"): "35",
            ("-s", "emulator-5554", "shell", "dumpsys", "user"): "UserInfo{0:Owner} UserInfo{10:Private}",
        }
    )

    class JavaVersionResult:
        stderr = 'openjdk version "17.0.9"\n'

    monkeypatch.setattr(
        "mcp_server.tools.system.subprocess.run",
        lambda *args, **kwargs: JavaVersionResult(),
    )

    return DoctorContext(adb=adb, roots_provider=lambda: [str(project_root)], env={"ANDROID_HOME": "/sdk"})


__all__ = ["MockAdb", "MockDevice", "MockSDKGateway"]
