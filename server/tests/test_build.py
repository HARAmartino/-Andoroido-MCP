from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from mcp_server.tools.build import BuildContext, _split_chunks, build_and_deploy


class FakeStream:
    def __init__(self, text: str) -> None:
        self._lines = [line.encode() for line in text.splitlines(keepends=True)]

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


@dataclass
class FakeProcess:
    returncode: int
    stdout_text: str = ""
    stderr_text: str = ""

    def __post_init__(self) -> None:
        self.stdout = FakeStream(self.stdout_text)
        self.stderr = FakeStream(self.stderr_text)

    async def wait(self) -> int:
        return self.returncode


class FakeSubprocessFactory:
    def __init__(self, responses: dict[tuple[str, ...], FakeProcess]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args, **_kwargs):
        key = tuple(args)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"Unexpected command: {key}")
        return self.responses[key]


@pytest.mark.asyncio
async def test_build_and_deploy_success_streams_and_reverses(tmp_path: Path) -> None:
    project_root = tmp_path / "android-app"
    project_root.mkdir()
    gradlew = project_root / "gradlew"
    gradlew.write_text("#!/bin/sh\n")

    apk_path = project_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    apk_path.parent.mkdir(parents=True)
    apk_path.write_text("fake-apk")

    device = "emulator-5554"
    factory = FakeSubprocessFactory(
        responses={
            (str(gradlew), "assembleDebug"): FakeProcess(
                returncode=0,
                stdout_text="Task :app:compileDebugKotlin\nTask :app:assembleDebug\nBUILD SUCCESSFUL\n",
            ),
            ("adb", "devices"): FakeProcess(
                returncode=0,
                stdout_text=f"List of devices attached\n{device}\tdevice\n",
            ),
            ("adb", "-s", device, "install", "-r", str(apk_path)): FakeProcess(
                returncode=0,
                stdout_text="Success\n",
            ),
            ("adb", "-s", device, "reverse", "tcp:8080", "tcp:8080"): FakeProcess(
                returncode=0,
                stdout_text="",
            ),
        }
    )
    context = BuildContext(
        roots_provider=lambda: [str(project_root)],
        subprocess_factory=factory,
        log_chunk_chars=30,
        max_log_chunks=10,
    )

    result = await build_and_deploy(context=context, clean=False, variant="debug")

    assert result["status"] == "success"
    assert result["apk_path"] == str(apk_path)
    assert len(result["build_log_chunks"]) >= 2
    assert any("BUILD SUCCESSFUL" in chunk for chunk in result["build_log_chunks"])
    assert result["adb_reverse"]["status"] == "ok"
    assert ("adb", "-s", device, "reverse", "tcp:8080", "tcp:8080") in factory.calls


@pytest.mark.asyncio
async def test_build_and_deploy_handles_private_space_locked(tmp_path: Path) -> None:
    project_root = tmp_path / "android-app"
    project_root.mkdir()
    gradlew = project_root / "gradlew"
    gradlew.write_text("#!/bin/sh\n")

    apk_path = project_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    apk_path.parent.mkdir(parents=True)
    apk_path.write_text("fake-apk")

    device = "emulator-5554"
    factory = FakeSubprocessFactory(
        responses={
            (str(gradlew), "assembleDebug"): FakeProcess(returncode=0, stdout_text="BUILD SUCCESSFUL\n"),
            ("adb", "devices"): FakeProcess(
                returncode=0,
                stdout_text=f"List of devices attached\n{device}\tdevice\n",
            ),
            ("adb", "-s", device, "install", "-r", str(apk_path)): FakeProcess(
                returncode=1,
                stderr_text="Failure [INSTALL_FAILED_USER_RESTRICTED]\n",
            ),
            ("adb", "-s", device, "shell", "dumpsys", "user"): FakeProcess(
                returncode=0,
                stdout_text="UserInfo{0:Owner} UserInfo{10:Private}\n",
            ),
            ("adb", "-s", device, "install", "-r", "--user", "10", str(apk_path)): FakeProcess(
                returncode=1,
                stderr_text="ERR_PRIVATE_SPACE_LOCKED\n",
            ),
        }
    )
    context = BuildContext(
        roots_provider=lambda: [str(project_root)],
        subprocess_factory=factory,
    )

    result = await build_and_deploy(context=context, clean=False, variant="debug")

    assert result["status"] == "error"
    assert result["error_code"] == "ERR_PRIVATE_SPACE_LOCKED"


def test_split_chunks_truncates_when_exceeding_limit() -> None:
    lines = [f"line-{i}" for i in range(10)]
    chunks = _split_chunks(lines=lines, max_chars=6, max_chunks=3)

    assert len(chunks) == 3
    assert chunks[1] == "...(truncated log chunks)..."
