from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


class AdbClient(Protocol):
    def run(self, *args: str) -> str:
        """Run adb command and return stdout as text."""


class SubprocessAdb:
    """Default ADB client that shells out to adb."""

    def run(self, *args: str) -> str:
        completed = subprocess.run(
            ["adb", *args],
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()


@dataclass(slots=True)
class DoctorContext:
    adb: AdbClient = field(default_factory=SubprocessAdb)
    roots_provider: Callable[[], list[str]] = field(default_factory=lambda: (lambda: []))
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))


def _find_gradlew(roots: list[str]) -> str | None:
    for root in roots:
        candidate = Path(root) / "gradlew"
        if candidate.exists():
            return str(candidate)
    return None


def _parse_first_connected_device(devices_output: str) -> str | None:
    for line in devices_output.splitlines():
        if "\tdevice" in line:
            return line.split("\t", maxsplit=1)[0].strip()
    return None


def _private_space_detected(dumpsys_output: str) -> bool:
    return "UserInfo{10:" in dumpsys_output or "serialNo=10" in dumpsys_output


def doctor(context: DoctorContext | None = None) -> str:
    """Diagnose local environment for Android MCP usage and return markdown report."""
    ctx = context or DoctorContext()

    lines: list[str] = ["## Android MCP Doctor Report", ""]

    android_home = ctx.env.get("ANDROID_HOME")
    lines.append(f"- ANDROID_HOME: {'✅ ' + android_home if android_home else '❌ not set'}")

    try:
        adb_version = ctx.adb.run("version")
        lines.append(f"- adb: ✅ {adb_version.splitlines()[0]}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        lines.append(f"- adb: ❌ {exc}")
        return "\n".join(lines)

    try:
        java_version = subprocess.run(
            ["java", "-version"],
            check=True,
            text=True,
            capture_output=True,
        ).stderr.strip().splitlines()[0]
        lines.append(f"- java: ✅ {java_version}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        lines.append(f"- java: ❌ {exc}")

    gradlew_path = _find_gradlew(ctx.roots_provider())
    lines.append(f"- gradlew via Roots: {'✅ ' + gradlew_path if gradlew_path else '❌ not found'}")

    try:
        devices_output = ctx.adb.run("devices")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        lines.append(f"- device connection: ❌ {exc}")
        return "\n".join(lines)

    serial = _parse_first_connected_device(devices_output)
    if not serial:
        lines.append("- device connection: ⚠️ no connected devices")
        return "\n".join(lines)

    lines.append(f"- device connection: ✅ {serial}")

    try:
        android_release = ctx.adb.run("-s", serial, "shell", "getprop", "ro.build.version.release")
        android_sdk = ctx.adb.run("-s", serial, "shell", "getprop", "ro.build.version.sdk")
        sdk_value = int(android_sdk.strip() or "0")
        lines.append(f"- android version: ✅ {android_release} (SDK {sdk_value})")
        if sdk_value >= 35:
            lines.append("- android 15+ check: ⚠️ Android 15+ detected. Verify Private Space constraints.")

        dumpsys_user = ctx.adb.run("-s", serial, "shell", "dumpsys", "user")
        if _private_space_detected(dumpsys_user):
            lines.append("- private space: ⚠️ Detected additional Android user profile(s); app may be in Private Space.")
        else:
            lines.append("- private space: ✅ no private profile indicators detected")
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as exc:
        lines.append(f"- android details: ⚠️ failed to inspect device details: {exc}")

    return "\n".join(lines)
