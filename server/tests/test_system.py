from __future__ import annotations

from mcp_server.tools.system import DoctorContext, doctor
from tests.helpers import MockJavaVersionResult


def test_doctor_report_includes_required_checks(doctor_context: DoctorContext) -> None:
    report = doctor(doctor_context)

    assert "ANDROID_HOME: ✅ /sdk" in report
    assert "adb: ✅ Android Debug Bridge version" in report
    assert "java: ✅ openjdk version" in report
    assert "gradlew via Roots: ✅" in report
    assert "device connection: ✅ emulator-5554" in report
    assert "android 15+ check: ⚠️" in report
    assert "private space: ⚠️" in report


def test_doctor_handles_no_connected_device(monkeypatch) -> None:
    class NoDeviceAdb:
        def run(self, *args: str) -> str:
            if args == ("version",):
                return "Android Debug Bridge version 1.0.41"
            if args == ("devices",):
                return "List of devices attached\n"
            raise AssertionError(args)

    def mock_subprocess_run(*args, **_kwargs):
        if list(args[0]) != ["java", "-version"]:
            raise AssertionError(f"Unexpected subprocess call: {args[0]}")
        return MockJavaVersionResult()

    monkeypatch.setattr("mcp_server.tools.system.subprocess.run", mock_subprocess_run)

    report = doctor(DoctorContext(adb=NoDeviceAdb(), roots_provider=lambda: [], env={}))

    assert "device connection: ⚠️ no connected devices" in report
