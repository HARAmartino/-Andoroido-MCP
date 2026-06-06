"""Autonomous UI fuzzing with crash detection."""
from __future__ import annotations

import random
import time
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from mcp_server.tools.crash import CrashContext, contains_crash_signature, get_crash_context

FuzzStrategy = Literal["random", "guided"]

logger = logging.getLogger(__name__)

SYSTEM_DIALOG_KEYWORDS: tuple[str, ...] = (
    "permission",
    "allow",
    "deny",
    "battery",
    "systemui",
    "com.android",
    "android.permissioncontroller",
)
# Exact package names (or their namespace prefixes) that are always system-owned.
# Checked against the node's `package` attribute to suppress bare text/content-desc
# selectors from nodes that have no resource-id to filter on.
_SYSTEM_PACKAGES: tuple[str, ...] = (
    "com.android.systemui",
    "com.android.settings",
    "com.google.android.systemui",
    "android",
)
# Guided strategy uses cumulative probabilities:
# click: [0.00, 0.75), scroll: [0.75, 0.95), swipe: [0.95, 1.00].
GUIDED_CLICK_PROB = 0.75
GUIDED_SCROLL_UPPER_PROB = 0.95
GUIDED_SWIPE_PROB = 1.0 - GUIDED_SCROLL_UPPER_PROB


class FuzzDevice(Protocol):
    def click(self, selector: str) -> None: ...

    def swipe(self, selector: str) -> None: ...

    def scroll(self, selector: str) -> None: ...

    def dump_hierarchy(self) -> str: ...

    def get_recent_logs(self, window_ms: int = 500) -> list[str]: ...


@dataclass(slots=True)
class FuzzContext:
    device: FuzzDevice
    crash_context: CrashContext
    record_action: Callable[[dict[str, Any]], None] | None = None
    random_source: random.Random = field(default_factory=random.Random)
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    step_delay_sec: float = 0.2
    recent_log_window_ms: int = 500


def _is_system_selector(value: str) -> bool:
    lowered = value.lower()
    return any(keyword in lowered for keyword in SYSTEM_DIALOG_KEYWORDS)


def _is_system_package(pkg: str) -> bool:
    """Return True when *pkg* is a known Android system package namespace."""
    return any(pkg == m or pkg.startswith(m + ".") for m in _SYSTEM_PACKAGES)


def _clean_selector(value: str) -> str:
    """Strip ASCII whitespace plus Unicode non-printable/zero-width chars."""
    return "".join(ch for ch in value if ch.isprintable()).strip()


def _candidate_selectors(xml_text: str) -> list[str]:
    selectors: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return selectors

    for node in root.iter("node"):
        # NAF="true" means the element is Not Accessibility Friendly; uiautomator2
        # cannot reliably interact with it, so skip it entirely.
        if node.attrib.get("NAF") == "true":
            continue

        pkg = node.attrib.get("package", "")
        rid = _clean_selector(node.attrib.get("resource-id", ""))

        # Always include non-system resource-ids (they're unambiguous selectors).
        if rid and not _is_system_selector(rid):
            selectors.append(rid)

        # Include text / content-desc only when the host package is NOT a system
        # package, preventing bare notification/status-bar text from leaking in.
        if _is_system_package(pkg):
            continue

        for key in ("text", "content-desc"):
            value = _clean_selector(node.attrib.get(key, ""))
            if not value or _is_system_selector(value):
                continue
            selectors.append(value)

    return selectors


def _pick_action(
    strategy: FuzzStrategy,
    selectors: list[str],
    rng: random.Random,
) -> tuple[str, str]:
    if not selectors:
        return ("scroll", "root")
    selector = rng.choice(selectors)
    if strategy == "guided":
        roll = rng.random()
        if roll < GUIDED_CLICK_PROB:
            action = "click"
        elif roll < GUIDED_SCROLL_UPPER_PROB:
            action = "scroll"
        else:
            action = "swipe"
    else:
        action = rng.choice(["click", "scroll", "swipe"])
    return (action, selector)


def _run_action(device: FuzzDevice, action: str, selector: str) -> None:
    if action == "click":
        device.click(selector)
        return
    if action == "scroll":
        device.scroll(selector)
        return
    if action == "swipe":
        device.swipe(selector)
        return
    raise ValueError(f"Unsupported fuzz action: {action}")


def start_fuzzing(
    context: FuzzContext,
    duration_sec: int,
    strategy: FuzzStrategy = "random",
    target_selector: str | None = None,
) -> dict[str, Any]:
    """Run random/guided actions and stop immediately when crash/ANR is observed."""
    if duration_sec <= 0:
        raise ValueError("duration_sec must be > 0")
    if strategy not in {"random", "guided"}:
        raise ValueError("strategy must be 'random' or 'guided'")

    deadline = context.clock() + duration_sec
    iterations = 0

    if target_selector:
        try:
            _run_action(context.device, "click", target_selector)
            action_status = "success"
        except RuntimeError:
            action_status = "failure"

        if context.record_action:
            context.record_action(
                {
                    "tool": "start_fuzzing",
                    "action": "click",
                    "selector": target_selector,
                    "status": action_status,
                }
            )

        iterations += 1
        logs = context.device.get_recent_logs(window_ms=context.recent_log_window_ms)
        if contains_crash_signature(logs):
            crash = get_crash_context(context.crash_context, log_lines=logs)
            crash["status"] = "stopped_on_crash"
            crash["fuzzing"] = {
                "status": "stopped_on_crash",
                "iterations": iterations,
                "strategy": strategy,
                "target_selector": target_selector,
            }
            return crash

    while context.clock() < deadline:
        selectors = _candidate_selectors(context.device.dump_hierarchy())
        action, selector = _pick_action(strategy, selectors, context.random_source)

        try:
            _run_action(context.device, action, selector)
            action_status = "success"
        except RuntimeError as exc:
            action_status = "failure"
            logger.debug("fuzz action failed: action=%s selector=%s error=%s", action, selector, exc)

        if context.record_action:
            context.record_action(
                {
                    "tool": "start_fuzzing",
                    "action": action,
                    "selector": selector,
                    "status": action_status,
                }
            )

        iterations += 1
        logs = context.device.get_recent_logs(window_ms=context.recent_log_window_ms)
        if contains_crash_signature(logs):
            crash = get_crash_context(context.crash_context, log_lines=logs)
            crash["status"] = "stopped_on_crash"
            crash["fuzzing"] = {
                "status": "stopped_on_crash",
                "iterations": iterations,
                "strategy": strategy,
                "target_selector": target_selector,
            }
            return crash

        context.sleeper(context.step_delay_sec)

    return {
        "status": "completed",
        "duration_sec": duration_sec,
        "strategy": strategy,
        "iterations": iterations,
    }
