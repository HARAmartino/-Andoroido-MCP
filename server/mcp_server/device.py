"""Adapter that bridges a real ``uiautomator2`` device to the ``DeviceClient`` protocol.

The MCP tools (``tools.ui``, ``tools.fuzz``, ``tools.crash``) talk to a small,
*selector-string* oriented interface (:class:`tools.ui.DeviceClient`):

    click(selector) / long_click(selector) / input_text(selector, value)
    swipe(selector) / scroll(selector) / dump_hierarchy() / get_recent_logs(window_ms)

A raw ``uiautomator2.Device`` does **not** implement that interface – its
``click``/``swipe`` take pixel coordinates, and it has no ``input_text``,
``scroll`` or ``get_recent_logs`` at all.  This adapter performs the translation
so the same tool code works against both ``MockDevice`` (tests) and a physical
device (production), satisfying the "abstract real-device logic behind an
interface" constraint.
"""
from __future__ import annotations

import subprocess
from typing import Any


class ElementNotFound(RuntimeError):
    """Raised when a selector string matches no on-screen element."""


# Approximate logcat line budget per millisecond of requested window.  A precise
# wall-clock window is unreliable across host/device clock skew, so we fetch a
# bounded recent tail instead and document this as best-effort.
_LOGCAT_LINES_PER_MS = 0.1
_LOGCAT_MIN_LINES = 50
_LOGCAT_MAX_LINES = 2000


def _parse_coord(selector: str) -> tuple[int, int] | None:
    """Parse a coordinate handle ``@x,y`` (emitted by the compact snapshot for
    actionable nodes lacking any id/text/desc) into ``(x, y)``; else ``None``."""
    if not selector or not selector.startswith("@"):
        return None
    import re

    m = re.fullmatch(r"@\s*(-?\d+)\s*,\s*(-?\d+)", selector.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


class UiAutomator2Adapter:
    """Wrap a ``uiautomator2.Device`` to satisfy :class:`tools.ui.DeviceClient`."""

    def __init__(self, device: Any, serial: str | None = None) -> None:  # noqa: ANN401
        self._d = device
        # Resolve the serial for logcat; fall back to the device's own handle.
        self._serial = serial or getattr(device, "serial", None)

    # ------------------------------------------------------------------
    # Selector resolution
    # ------------------------------------------------------------------

    def _resolve(self, selector: str) -> Any:  # noqa: ANN401
        """Return a uiautomator2 UiObject for *selector*, trying several strategies.

        Mirrors ``MockDevice._ensure_element_present``: a selector may be a full
        resource-id (``com.example:id/btn``), a bare id suffix (``btn``), visible
        text, or a content-description.
        """
        d = self._d
        # 1. Exact resource-id.
        el = d(resourceId=selector)
        if el.exists:
            return el
        # 2. resource-id suffix (bare id like "btn_login").
        el = d(resourceIdMatches=rf".*[:/]{_re_escape(selector)}$")
        if el.exists:
            return el
        # 3. Exact visible text.
        el = d(text=selector)
        if el.exists:
            return el
        # 4. Content description.
        el = d(description=selector)
        if el.exists:
            return el
        raise ElementNotFound(f"ElementNotFound: {selector}")

    # ------------------------------------------------------------------
    # DeviceClient protocol
    # ------------------------------------------------------------------

    def click(self, selector: str) -> None:
        coord = _parse_coord(selector)
        if coord is not None:
            self._d.click(*coord)
            return
        self._resolve(selector).click()

    def long_click(self, selector: str) -> None:
        coord = _parse_coord(selector)
        if coord is not None:
            self._d.long_click(*coord)
            return
        self._resolve(selector).long_click()

    def input_text(self, selector: str, value: str) -> None:
        el = self._resolve(selector)
        el.click()  # focus the field first
        el.set_text(value)

    def swipe(self, selector: str) -> None:
        # Swipe within the bounds of the matched element (default: upward).
        self._resolve(selector).swipe("up")

    def scroll(self, selector: str) -> None:
        el = self._resolve(selector)
        # Prefer a real scroll gesture; fall back to an upward swipe if the
        # element is not itself scrollable.
        scroll = getattr(el, "scroll", None)
        if scroll is not None:
            try:
                scroll.vert.forward()
                return
            except Exception:  # noqa: BLE001 – fall back to swipe
                pass
        el.swipe("up")

    def dump_hierarchy(self) -> str:
        return self._d.dump_hierarchy()

    def screenshot(self) -> bytes:
        """Return the current screen as PNG bytes (full resolution).

        Downscaling/token-budgeting is handled by ``tools.ui.capture_screenshot``;
        this adapter only bridges uiautomator2's PIL screenshot to raw PNG bytes.
        """
        import io

        img = self._d.screenshot(format="pillow")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def get_recent_logs(self, window_ms: int = 500) -> list[str]:
        """Return a recent tail of logcat as individual lines.

        ``window_ms`` is honoured *approximately*: it is mapped to a bounded line
        budget rather than a precise time window, which avoids host/device clock
        skew while still giving "more time → more lines" behaviour.
        """
        lines = int(window_ms * _LOGCAT_LINES_PER_MS)
        lines = max(_LOGCAT_MIN_LINES, min(_LOGCAT_MAX_LINES, lines))
        cmd = ["adb"]
        if self._serial:
            cmd += ["-s", str(self._serial)]
        cmd += ["logcat", "-d", "-t", str(lines)]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, check=True
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return []
        return out.splitlines()


def _re_escape(value: str) -> str:
    import re

    return re.escape(value)
