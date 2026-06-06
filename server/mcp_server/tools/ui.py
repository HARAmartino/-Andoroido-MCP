from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol
import re
import xml.etree.ElementTree as ET

from mcp_server.sdk_bridge import _apply_string_patterns


ActionType = Literal["click", "long_click", "input", "swipe", "scroll"]
UIFormat = Literal["json", "xml", "summary", "compact"]
DEFAULT_LOG_WINDOW_MS = 500
DEFAULT_LOG_LINES = 10

# Token-budget caps for the compact snapshot. Borrowed from how PC/browser
# operating agents return an accessibility snapshot instead of the raw tree:
# only actionable/meaningful nodes, short refs, truncated text.
COMPACT_MAX_TEXT = 48
COMPACT_MAX_NODES = 80


class DeviceClient(Protocol):
    def click(self, selector: str) -> None: ...

    def long_click(self, selector: str) -> None: ...

    def input_text(self, selector: str, value: str) -> None: ...

    def swipe(self, selector: str) -> None: ...

    def scroll(self, selector: str) -> None: ...

    def dump_hierarchy(self) -> str: ...

    def get_recent_logs(self, window_ms: int = 500) -> list[str]: ...

    def screenshot(self) -> bytes: ...


class SDKGateway(Protocol):
    def is_connected(self) -> bool: ...


@dataclass(slots=True)
class UIContext:
    device: DeviceClient
    sdk_gateway: SDKGateway | None = None


def _sanitize_ui_text(value: str | None) -> str | None:
    """Apply string-level sanitization to a single UI node attribute value."""
    if not value:
        return value
    return _apply_string_patterns(value)


def _xml_to_summary(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    entries: list[str] = []
    for node in root.iter("node"):
        resource_id = node.attrib.get("resource-id")
        text = _sanitize_ui_text(node.attrib.get("text"))
        content_desc = _sanitize_ui_text(node.attrib.get("content-desc"))
        if resource_id or text or content_desc:
            entries.append(
                " | ".join(
                    part
                    for part in [
                        f"id={resource_id}" if resource_id else "",
                        f"text={text}" if text else "",
                        f"desc={content_desc}" if content_desc else "",
                    ]
                    if part
                )
            )
    if not entries:
        return "No meaningful UI nodes found."
    return "\n".join(f"- {entry}" for entry in entries)


def _strip_pkg(resource_id: str | None) -> str | None:
    """Drop the redundant `package:id/` prefix so it isn't repeated every line."""
    if not resource_id:
        return None
    return resource_id.split("/", 1)[1] if "/" in resource_id else resource_id


def _bounds_center(bounds: str | None) -> tuple[int, int] | None:
    """Parse uiautomator ``bounds="[x1,y1][x2,y2]"`` into a center ``(x, y)``."""
    if not bounds:
        return None
    nums = re.findall(r"-?\d+", bounds)
    if len(nums) < 4:
        return None
    x1, y1, x2, y2 = (int(n) for n in nums[:4])
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _node_role(node_class: str, attrib: dict[str, str]) -> str | None:
    """Classify a node into a short actionable role, or None if not worth emitting."""
    cls = (node_class or "").lower()
    truthy = {k for k, v in attrib.items() if v == "true"}

    if "edittext" in cls or attrib.get("class", "").endswith("EditText"):
        return "input"
    if "checkbox" in cls or "switch" in cls or "toggle" in cls or "checkable" in truthy:
        state = "on" if "checked" in truthy else "off"
        return f"toggle:{state}"
    if "scrollable" in truthy:
        return "scroll"
    if {"clickable", "long-clickable"} & truthy:
        if "button" in cls or "imagebutton" in cls or "imageview" in cls:
            return "button"
        return "tap"
    # Non-interactive but carries readable text/desc -> informational only.
    return "text"


def _xml_to_compact(xml_text: str) -> str:
    """Accessibility-style snapshot: only actionable/meaningful nodes, one line each.

    Format per line:  `[role] "text" -> #selector`
    The selector token (id > text > desc) is what `interact_and_observe` accepts,
    so the model never needs the raw tree to act. Mirrors how PC/browser agents
    return a pruned a11y snapshot with stable handles instead of the full DOM.
    """
    root = ET.fromstring(xml_text)
    lines: list[str] = []
    truncated = 0

    for node in root.iter("node"):
        attrib = node.attrib
        text = _sanitize_ui_text(attrib.get("text"))
        desc = _sanitize_ui_text(attrib.get("content-desc"))
        rid = _strip_pkg(attrib.get("resource-id"))
        truthy = {k for k, v in attrib.items() if v == "true"}
        interactive = bool(
            {"clickable", "long-clickable", "checkable", "scrollable", "focusable"} & truthy
        ) or "EditText" in attrib.get("class", "")

        # Keep a node only if it is interactive OR carries readable content.
        if not interactive and not text and not desc:
            continue

        role = _node_role(attrib.get("class", ""), attrib)
        label = (text or desc or "").strip()
        if len(label) > COMPACT_MAX_TEXT:
            label = label[: COMPACT_MAX_TEXT - 1] + "…"

        # Selector the action tools can resolve: prefer id, then exact text/desc.
        selector = rid or text or desc
        parts = [f"[{role}]"]
        if label:
            parts.append(f'"{label}"')
        if selector and selector == rid:
            parts.append(f"-> #{rid}")
        elif selector:
            parts.append(f"-> \"{selector[:COMPACT_MAX_TEXT]}\"")
        elif interactive:
            # Actionable node with no id/text/desc (icon-only button, Compose
            # node without semantics). Fall back to a stateless coordinate handle
            # so the agent is not blind to it. No cross-call state -> no staleness.
            center = _bounds_center(attrib.get("bounds"))
            if center:
                parts.append(f"-> @{center[0]},{center[1]}")

        if len(lines) >= COMPACT_MAX_NODES:
            truncated += 1
            continue
        lines.append(" ".join(parts))

    if not lines:
        return "No actionable UI nodes found."
    out = "\n".join(f"- {ln}" for ln in lines)
    if truncated:
        out += f"\n- (+{truncated} more nodes; use format='summary' or 'xml' for the full tree)"
    return out


def _xml_to_json(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)

    def walk(node: ET.Element) -> dict[str, Any]:
        return {
            "tag": node.tag,
            "attributes": dict(node.attrib),
            "children": [walk(child) for child in node],
        }

    return walk(root)


def get_ui_tree(context: UIContext, format: UIFormat = "compact") -> dict[str, Any]:
    """Return current UI hierarchy.

    Formats, cheapest to most expensive in tokens:
    - ``compact`` (default): a11y-style snapshot, actionable nodes only (~80-95%
      smaller than ``xml``). Preferred for normal navigation.
    - ``summary``: every node carrying id/text/desc.
    - ``xml`` / ``json``: full raw hierarchy. Use only when you truly need every node.
    """
    xml_text = context.device.dump_hierarchy()
    if format == "xml":
        return {"format": "xml", "tree": xml_text}
    if format == "json":
        return {"format": "json", "tree": _xml_to_json(xml_text)}
    if format == "summary":
        return {"format": "summary", "tree": _xml_to_summary(xml_text)}
    return {"format": "compact", "tree": _xml_to_compact(xml_text)}


COMPACT_DIFF_MAX_LINES = 20


def _compact_diff(before_xml: str, after_xml: str) -> str:
    """Token-lean post-action observation: only the compact nodes that changed.

    Returns added (`+`) / removed (`-`) actionable lines so the agent can pick its
    next action without a separate `get_ui_tree` round-trip. Falls back to a plain
    "no change" marker when the actionable surface is identical.
    """
    if before_xml == after_xml:
        return "No UI change detected"

    before = _xml_to_compact(before_xml).splitlines()
    after = _xml_to_compact(after_xml).splitlines()
    before_set = set(before)
    after_set = set(after)

    # Preserve on-screen order; strip the leading "- " bullet from compact lines.
    removed = [ln[2:] if ln.startswith("- ") else ln for ln in before if ln not in after_set]
    added = [ln[2:] if ln.startswith("- ") else ln for ln in after if ln not in before_set]

    if not removed and not added:
        # Raw XML differed (e.g. coordinates) but actionable surface is unchanged.
        return "UI changed (no actionable difference)"

    lines: list[str] = []
    for ln in removed[:COMPACT_DIFF_MAX_LINES]:
        lines.append(f"- − {ln}")
    if len(removed) > COMPACT_DIFF_MAX_LINES:
        lines.append(f"- (+{len(removed) - COMPACT_DIFF_MAX_LINES} more removed)")
    for ln in added[:COMPACT_DIFF_MAX_LINES]:
        lines.append(f"- ＋ {ln}")
    if len(added) > COMPACT_DIFF_MAX_LINES:
        lines.append(f"- (+{len(added) - COMPACT_DIFF_MAX_LINES} more added)")
    return "UI changed\n" + "\n".join(lines)


SCREENSHOT_DEFAULT_MAX_WIDTH = 720


def _downscale_png(raw: bytes, max_width: int) -> bytes:
    """Downscale a PNG to ``max_width`` to bound token cost; pass through on error."""
    if max_width <= 0:
        return raw
    try:
        import io

        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(raw))
        if img.width <= max_width:
            return raw
        ratio = max_width / float(img.width)
        resized = img.resize((max_width, max(1, int(img.height * ratio))))
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 – never fail the fallback on imaging issues
        return raw


def capture_screenshot(
    context: UIContext, max_width: int = SCREENSHOT_DEFAULT_MAX_WIDTH
) -> bytes:
    """Visual fallback: capture a downscaled PNG of the current screen.

    Use ONLY when the compact/summary text tree is insufficient — e.g. Compose /
    Canvas / WebView / game screens that expose no semantics, or when visual
    verification (color, layout, image content) is required. A text snapshot is
    far cheaper, so this is an explicit escape hatch, never the default.

    PRIVACY: a screenshot captures whatever is on screen verbatim, including any
    PII. It cannot be text-sanitized. Treat the result as ephemeral model context
    only — do NOT write it into bug reports, session history, or persisted logs.
    The image is downscaled to bound both token cost and incidental detail.
    """
    raw = context.device.screenshot()
    return _downscale_png(raw, max_width)


def _run_action(context: UIContext, action: ActionType, selector: str, value: str | None) -> None:
    if action == "click":
        context.device.click(selector)
    elif action == "long_click":
        context.device.long_click(selector)
    elif action == "input":
        if value is None:
            raise ValueError("value is required for input action")
        context.device.input_text(selector, value)
    elif action == "swipe":
        context.device.swipe(selector)
    elif action == "scroll":
        context.device.scroll(selector)
    else:
        raise ValueError(f"UnsupportedAction: {action}")


def interact_and_observe(
    context: UIContext,
    action: ActionType,
    selector: str,
    value: str | None = None,
) -> dict[str, Any]:
    """Perform UI action and return markdown result with UI diff and recent logs."""
    if action == "input" and value is None:
        return {
            "status": "requires_elicitation",
            "prompt": f"Please provide a value to input into selector '{selector}'.",
            "context_id": f"input:{selector}",
        }

    before_xml = context.device.dump_hierarchy()

    try:
        _run_action(context, action, selector, value)
        action_result = "✅ Success"
    except (ValueError, RuntimeError) as exc:
        action_result = f"❌ Failure: {action} on '{selector}' - {exc}"

    after_xml = context.device.dump_hierarchy()
    ui_diff = _compact_diff(before_xml, after_xml)
    logs = context.device.get_recent_logs(window_ms=DEFAULT_LOG_WINDOW_MS)
    log_snippet = "\n".join(f"- {line}" for line in logs[-DEFAULT_LOG_LINES:]) if logs else "- (no logs)"

    if "\n" in ui_diff:
        ui_diff_block = "2. **UI Diff**:\n" + ui_diff
    else:
        ui_diff_block = f"2. **UI Diff**: {ui_diff}"

    report = "\n".join(
        [
            "## interact_and_observe",
            "",
            f"1. **Action Result**: {action_result}",
            ui_diff_block,
            "3. **Logcat Snippet**:",
            log_snippet,
        ]
    )

    return {"text": report, "success": action_result == "✅ Success"}
