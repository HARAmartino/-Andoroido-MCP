from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import pytest

from mcp_server.tools.system import DoctorContext
from mcp_server.tools.ui import UIContext
from tests.helpers import MockJavaVersionResult

TEST_DEVICE_SERIAL = "emulator-5554"


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
        self._ensure_element_present(selector)
        root = ET.fromstring(self.current_xml)
        for node in root.iter("node"):
            resource_id = node.attrib.get("resource-id", "")
            if resource_id.endswith("btn_login"):
                node.set("text", "Login successful")
                break
        self.current_xml = ET.tostring(root, encoding="unicode")
        self.logs.append("I ActivityManager: click(Login)")

    def long_click(self, selector: str) -> None:
        self._ensure_element_present(selector)
        self.logs.append("I ActivityManager: long_click")

    def input_text(self, selector: str, value: str) -> None:
        self._ensure_element_present(selector)
        root = ET.fromstring(self.current_xml)
        for node in root.iter("node"):
            resource_id = node.attrib.get("resource-id", "")
            if resource_id.endswith(selector) or resource_id == selector:
                node.set("text", value)
                break
        self.current_xml = ET.tostring(root, encoding="unicode")
        self.logs.append(f"I InputMethod: set_text({selector})")

    def swipe(self, selector: str) -> None:
        self._ensure_element_present(selector)
        self.logs.append("I ViewRootImpl: swipe")

    def scroll(self, selector: str) -> None:
        self._ensure_element_present(selector)
        self.logs.append("I ViewRootImpl: scroll")

    def dump_hierarchy(self) -> str:
        return self.current_xml

    def get_recent_logs(self, window_ms: int = 500) -> list[str]:
        _ = window_ms
        return list(self.logs)

    def _ensure_element_present(self, selector: str) -> None:
        root = ET.fromstring(self.current_xml)
        for node in root.iter("node"):
            resource_id = node.attrib.get("resource-id", "")
            text = node.attrib.get("text", "")
            content_desc = node.attrib.get("content-desc", "")
            if selector in {resource_id, text, content_desc}:
                return
            if resource_id.split("/")[-1] == selector:
                return
            if ":id/" in resource_id and resource_id.split(":id/", maxsplit=1)[-1] == selector:
                return
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
            ("devices",): f"List of devices attached\n{TEST_DEVICE_SERIAL}\tdevice",
            ("-s", TEST_DEVICE_SERIAL, "shell", "getprop", "ro.build.version.release"): "15",
            ("-s", TEST_DEVICE_SERIAL, "shell", "getprop", "ro.build.version.sdk"): "35",
            ("-s", TEST_DEVICE_SERIAL, "shell", "dumpsys", "user"): "UserInfo{0:Owner} UserInfo{10:Private}",
        }
    )

    def mock_subprocess_run(*args, **_kwargs):
        if list(args[0]) != ["java", "-version"]:
            raise AssertionError(f"Unexpected subprocess call: {args[0]}")
        return MockJavaVersionResult()

    monkeypatch.setattr("mcp_server.tools.system.subprocess.run", mock_subprocess_run)

    return DoctorContext(adb=adb, roots_provider=lambda: [str(project_root)], env={"ANDROID_HOME": "/sdk"})


__all__ = ["MockAdb", "MockDevice", "MockSDKGateway", "MockJavaVersionResult"]
