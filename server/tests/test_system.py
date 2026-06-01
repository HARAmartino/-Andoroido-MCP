from __future__ import annotations

from mcp_server.tools.system import DoctorContext, doctor


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

    class JavaVersionResult:
        stderr = 'openjdk version "17.0.9"\n'

    monkeypatch.setattr(
        "mcp_server.tools.system.subprocess.run",
        lambda *args, **kwargs: JavaVersionResult(),
    )

    report = doctor(DoctorContext(adb=NoDeviceAdb(), roots_provider=lambda: [], env={}))

    assert "device connection: ⚠️ no connected devices" in report
