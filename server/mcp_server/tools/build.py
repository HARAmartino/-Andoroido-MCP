from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from mcp_server.tools.system import _find_gradlew, _parse_first_connected_device, _private_space_detected

DEFAULT_LOG_CHUNK_CHARS = 2000
DEFAULT_MAX_LOG_CHUNKS = 30
PRIVATE_SPACE_USER_ID = 10


class AsyncLineReader(Protocol):
    async def readline(self) -> bytes: ...


class AsyncProcess(Protocol):
    stdout: AsyncLineReader | None
    stderr: AsyncLineReader | None

    async def wait(self) -> int: ...


SubprocessFactory = Callable[..., Awaitable[AsyncProcess]]


def _empty_roots_provider() -> list[str]:
    return []


@dataclass(slots=True)
class BuildContext:
    roots_provider: Callable[[], list[str]] = _empty_roots_provider
    subprocess_factory: SubprocessFactory = asyncio.create_subprocess_exec
    adb_path: str = "adb"
    log_chunk_chars: int = DEFAULT_LOG_CHUNK_CHARS
    max_log_chunks: int = DEFAULT_MAX_LOG_CHUNKS


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _assemble_task(variant: str) -> str:
    normalized = (variant or "debug").strip()
    if not normalized:
        normalized = "debug"
    return f"assemble{normalized[:1].upper()}{normalized[1:]}"


def _split_chunks(lines: list[str], max_chars: int, max_chunks: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        text = line if len(line) <= max_chars else f"{line[: max(0, max_chars - 16)]}...(truncated)..."
        next_size = current_size + len(text) + (1 if current else 0)
        if current and next_size > max_chars:
            chunks.append("\n".join(current))
            current = [text]
            current_size = len(text)
        else:
            current.append(text)
            current_size = next_size
    if current:
        chunks.append("\n".join(current))

    if len(chunks) <= max_chunks:
        return chunks
    head = chunks[: max_chunks // 2]
    tail = chunks[-(max_chunks - len(head) - 1) :]
    return [*head, "...(truncated log chunks)...", *tail]


async def _read_lines(stream: AsyncLineReader | None) -> list[str]:
    if stream is None:
        return []
    lines: list[str] = []
    while True:
        raw = await stream.readline()
        if not raw:
            break
        lines.append(raw.decode(errors='replace').rstrip())
    return lines


async def _run_command(
    context: BuildContext,
    command: list[str],
    cwd: Path | None = None,
) -> CommandResult:
    process = await context.subprocess_factory(
        *command,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_lines_task = asyncio.create_task(_read_lines(process.stdout))
    stderr_lines_task = asyncio.create_task(_read_lines(process.stderr))
    returncode = await process.wait()
    stdout_lines = await stdout_lines_task
    stderr_lines = await stderr_lines_task
    return CommandResult(
        returncode=returncode,
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
    )


def _find_apk(project_root: Path, variant: str) -> Path | None:
    variant_lower = variant.lower()
    preferred = sorted(project_root.glob(f"**/*{variant_lower}*.apk"))
    if preferred:
        return preferred[-1]
    all_apks = sorted(project_root.glob("**/*.apk"))
    if all_apks:
        return all_apks[-1]
    return None


def _is_private_space_locked(stderr: str, stdout: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    return "err_private_space_locked" in combined or "install_failed_user_restricted" in combined


async def _ensure_adb_reverse(context: BuildContext, serial: str | None = None) -> CommandResult:
    command = [context.adb_path]
    if serial:
        command.extend(["-s", serial])
    command.extend(["reverse", "tcp:8080", "tcp:8080"])
    return await _run_command(context, command)


def ensure_adb_reverse_on_startup(adb_path: str = "adb") -> bool:
    try:
        subprocess.run(
            [adb_path, "reverse", "tcp:8080", "tcp:8080"],
            check=True,
            text=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


async def build_and_deploy(
    context: BuildContext | None = None,
    clean: bool = False,
    variant: str = "debug",
) -> dict[str, Any]:
    ctx = context or BuildContext()
    gradlew = _find_gradlew(ctx.roots_provider())
    if not gradlew:
        return {
            "status": "error",
            "error_code": "GradleNotFound",
            "message": "Could not locate gradlew via Roots.",
        }

    gradlew_path = Path(gradlew)
    project_root = gradlew_path.parent
    build_tasks = [_assemble_task(variant)]
    if clean:
        build_tasks.insert(0, "clean")

    build_result = await _run_command(ctx, [str(gradlew_path), *build_tasks], cwd=project_root)
    build_lines = [line for line in [build_result.stdout, build_result.stderr] if line]
    build_chunks = _split_chunks(
        "\n".join(build_lines).splitlines(),
        max_chars=ctx.log_chunk_chars,
        max_chunks=ctx.max_log_chunks,
    )

    if build_result.returncode != 0:
        return {
            "status": "build_failed",
            "task": " ".join(build_tasks),
            "gradlew": str(gradlew_path),
            "build_log_chunks": build_chunks,
        }

    apk_path = _find_apk(project_root, variant)
    if not apk_path:
        return {
            "status": "error",
            "error_code": "ApkNotFound",
            "message": f"Build succeeded but no APK found for variant '{variant}'.",
            "build_log_chunks": build_chunks,
        }

    devices = await _run_command(ctx, [ctx.adb_path, "devices"])
    serial = _parse_first_connected_device(devices.stdout)
    if not serial:
        return {
            "status": "error",
            "error_code": "NoDevice",
            "message": "No connected Android device detected.",
            "build_log_chunks": build_chunks,
        }

    install_cmd = [ctx.adb_path, "-s", serial, "install", "-r", str(apk_path)]
    install_result = await _run_command(ctx, install_cmd)
    private_space_retry = False

    if install_result.returncode != 0 and _is_private_space_locked(install_result.stderr, install_result.stdout):
        dumpsys = await _run_command(ctx, [ctx.adb_path, "-s", serial, "shell", "dumpsys", "user"])
        if _private_space_detected(f"{dumpsys.stdout}\n{dumpsys.stderr}"):
            private_space_retry = True
            retry_cmd = [ctx.adb_path, "-s", serial, "install", "-r", "--user", str(PRIVATE_SPACE_USER_ID), str(apk_path)]
            install_result = await _run_command(ctx, retry_cmd)
            if install_result.returncode != 0:
                return {
                    "status": "error",
                    "error_code": "ERR_PRIVATE_SPACE_LOCKED",
                    "message": "Install failed for Private Space user. Unlock Private Space and retry.",
                    "build_log_chunks": build_chunks,
                    "install_stdout": install_result.stdout,
                    "install_stderr": install_result.stderr,
                }

    if install_result.returncode != 0:
        return {
            "status": "error",
            "error_code": "InstallFailed",
            "message": "APK installation failed.",
            "build_log_chunks": build_chunks,
            "install_stdout": install_result.stdout,
            "install_stderr": install_result.stderr,
        }

    reverse_result = await _ensure_adb_reverse(ctx, serial=serial)
    reverse_status = "ok" if reverse_result.returncode == 0 else "failed"

    return {
        "status": "success",
        "variant": variant,
        "task": " ".join(build_tasks),
        "gradlew": str(gradlew_path),
        "apk_path": str(apk_path),
        "build_log_chunks": build_chunks,
        "install_stdout": install_result.stdout,
        "private_space_retry": private_space_retry,
        "adb_reverse": {
            "status": reverse_status,
            "stdout": reverse_result.stdout,
            "stderr": reverse_result.stderr,
        },
    }
