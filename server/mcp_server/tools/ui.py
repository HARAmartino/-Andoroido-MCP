from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol
import xml.etree.ElementTree as ET


ActionType = Literal["click", "long_click", "input", "swipe", "scroll"]
UIFormat = Literal["json", "xml", "summary"]


class DeviceClient(Protocol):
    def click(self, selector: str) -> None: ...

    def long_click(self, selector: str) -> None: ...

    def input_text(self, selector: str, value: str) -> None: ...

    def swipe(self, selector: str) -> None: ...

    def scroll(self, selector: str) -> None: ...

    def dump_hierarchy(self) -> str: ...

    def get_recent_logs(self, window_ms: int = 500) -> list[str]: ...


class SDKGateway(Protocol):
    def is_connected(self) -> bool: ...


@dataclass(slots=True)
class UIContext:
    device: DeviceClient
    sdk_gateway: SDKGateway | None = None


def _xml_to_summary(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    entries: list[str] = []
    for node in root.iter("node"):
        resource_id = node.attrib.get("resource-id")
        text = node.attrib.get("text")
        content_desc = node.attrib.get("content-desc")
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


def _xml_to_json(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)

    def walk(node: ET.Element) -> dict[str, Any]:
        return {
            "tag": node.tag,
            "attributes": dict(node.attrib),
            "children": [walk(child) for child in node],
        }

    return walk(root)


def get_ui_tree(context: UIContext, format: UIFormat = "summary") -> dict[str, Any]:
    """Return current UI hierarchy as summary, XML, or JSON representation."""
    xml_text = context.device.dump_hierarchy()
    if format == "xml":
        return {"format": "xml", "tree": xml_text}
    if format == "json":
        return {"format": "json", "tree": _xml_to_json(xml_text)}
    return {"format": "summary", "tree": _xml_to_summary(xml_text)}


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
    except Exception as exc:  # noqa: BLE001 - returned as tool output
        action_result = f"❌ Failure: {exc}"

    after_xml = context.device.dump_hierarchy()
    ui_diff = "UI changed" if before_xml != after_xml else "No UI change detected"
    logs = context.device.get_recent_logs(window_ms=500)
    log_snippet = "\n".join(f"- {line}" for line in logs[-10:]) if logs else "- (no logs)"

    report = "\n".join(
        [
            "## interact_and_observe",
            "",
            f"1. **Action Result**: {action_result}",
            f"2. **UI Diff**: {ui_diff}",
            "3. **Logcat Snippet**:",
            log_snippet,
        ]
    )

    return {"text": report}
