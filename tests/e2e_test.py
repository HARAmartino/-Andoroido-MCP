from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from mcp_server.main import build_and_deploy, generate_bug_report, interact_and_observe, runtime, start_fuzzing
from mcp_server.sdk_bridge import bridge


def _assert_markdown_sane(markdown: str) -> None:
    required_sections = [
        "# E2E Crash Validation",
        "## Reproduction Steps",
        "## Crash Context",
        "## Log Snippet",
        "## Network Traces",
    ]
    for section in required_sections:
        if section not in markdown:
            raise AssertionError(f"Missing markdown section: {section}")

    if "```json" not in markdown or "```text" not in markdown:
        raise AssertionError("Bug report markdown must include fenced code blocks")

    forbidden = [
        r"Authorization:\s*Bearer\s+(?!\*\*\*MASKED\*\*\*)",
        r'"password"\s*:\s*"(?!\*\*\*MASKED\*\*\*)',
        r'"token"\s*:\s*"(?!\*\*\*MASKED\*\*\*)',
    ]
    for pattern in forbidden:
        if re.search(pattern, markdown):
            raise AssertionError(f"Found unmasked sensitive value in bug report: {pattern}")


def _launch_app(package_name: str) -> None:
    subprocess.run(
        ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
        check=True,
        capture_output=True,
        text=True,
    )


async def run_e2e(args: argparse.Namespace) -> None:
    demo_app_root = (REPO_ROOT / "sdk" / "demo-app").resolve()
    runtime.set_roots([str(demo_app_root)])

    bridge_server_task = asyncio.create_task(bridge.serve(host="127.0.0.1", port=8080))

    try:
        build_result = await build_and_deploy(clean=False, variant="debug")
        if build_result.get("status") != "success":
            raise AssertionError(f"build_and_deploy failed: {build_result}")

        _launch_app(args.package)

        sdk_connected = await bridge.wait_for_event("SDK_CONNECTED", timeout_sec=args.connect_timeout_sec)
        if not sdk_connected:
            raise AssertionError("SDK_CONNECTED event not observed within timeout")

        interact_and_observe(action="click", selector=args.network_selector)
        await asyncio.sleep(args.network_settle_sec)

        fuzz_result = start_fuzzing(
            duration_sec=args.fuzz_duration_sec,
            strategy="guided",
            target_selector=args.crash_selector,
        )

        if fuzz_result.get("status") != "stopped_on_crash":
            raise AssertionError(f"Expected stopped_on_crash, got: {fuzz_result.get('status')}")

        if not fuzz_result.get("stack_trace"):
            raise AssertionError("Expected stack trace in fuzzing result")

        if not fuzz_result.get("network_traces"):
            raise AssertionError("Expected network traces in fuzzing result")

        report = generate_bug_report(
            title="E2E Crash Validation",
            steps=[
                "Build and deploy demo app",
                "Tap Network Button",
                "Start fuzzing with Crash Button target",
            ],
            crash_context=fuzz_result,
            logs=fuzz_result.get("stack_trace", []),
            network_traces=fuzz_result.get("network_traces", []),
        )

        markdown = report.get("text", "")
        _assert_markdown_sane(markdown)
        print("E2E test passed")
    finally:
        bridge_server_task.cancel()
        await asyncio.gather(bridge_server_task, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 real-device E2E validation")
    parser.add_argument("--package", default="com.android.mcp.demo")
    parser.add_argument("--crash-selector", default="btn_crash")
    parser.add_argument("--network-selector", default="btn_network")
    parser.add_argument("--connect-timeout-sec", type=float, default=30.0)
    parser.add_argument("--network-settle-sec", type=float, default=2.0)
    parser.add_argument("--fuzz-duration-sec", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run_e2e(args))


if __name__ == "__main__":
    main()
