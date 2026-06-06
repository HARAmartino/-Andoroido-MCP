from __future__ import annotations

from mcp_server.tools.ui import (
    _bounds_center,
    _compact_diff,
    _downscale_png,
    _xml_to_compact,
    capture_screenshot,
    get_ui_tree,
    interact_and_observe,
)


def test_bounds_center_parses_uiautomator_bounds() -> None:
    assert _bounds_center("[0,0][100,40]") == (50, 20)
    assert _bounds_center(None) is None
    assert _bounds_center("garbage") is None


def test_compact_coordinate_fallback_for_selectorless_node() -> None:
    # Icon-only button: clickable but no id/text/desc -> stateless @x,y handle.
    xml = (
        '<hierarchy><node class="android.widget.ImageButton" clickable="true" '
        'bounds="[10,20][110,80]" /></hierarchy>'
    )
    out = _xml_to_compact(xml)
    assert "-> @60,50" in out


def test_capture_screenshot_returns_png_bytes(ui_context) -> None:
    data = capture_screenshot(context=ui_context, max_width=720)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_downscale_png_passthrough_on_small_image(ui_context) -> None:
    raw = ui_context.device.screenshot()
    # 2px-wide source, max_width well above it -> unchanged passthrough.
    assert _downscale_png(raw, max_width=720) == raw


def test_compact_diff_no_change_when_identical() -> None:
    xml = '<hierarchy><node class="android.widget.Button" text="A" clickable="true" /></hierarchy>'
    assert _compact_diff(xml, xml) == "No UI change detected"


def test_compact_diff_reports_added_and_removed() -> None:
    before = '<hierarchy><node class="android.widget.Button" text="ログイン" clickable="true" /></hierarchy>'
    after = '<hierarchy><node class="android.widget.Button" text="ログアウト" clickable="true" /></hierarchy>'
    out = _compact_diff(before, after)

    assert out.startswith("UI changed")
    assert "− [button] \"ログイン\"" in out  # removed actionable node
    assert "＋ [button] \"ログアウト\"" in out  # added actionable node


def test_compact_diff_ignores_non_actionable_xml_changes() -> None:
    # Only bounds/coordinates differ -> actionable surface unchanged.
    before = '<hierarchy><node class="android.widget.Button" text="A" clickable="true" bounds="[0,0][1,1]" /></hierarchy>'
    after = '<hierarchy><node class="android.widget.Button" text="A" clickable="true" bounds="[5,5][6,6]" /></hierarchy>'
    assert _compact_diff(before, after) == "UI changed (no actionable difference)"


def test_get_ui_tree_defaults_to_compact(ui_context) -> None:
    result = get_ui_tree(context=ui_context)

    assert result["format"] == "compact"
    # Node carrying text is surfaced with its package-stripped selector.
    assert '[text] "Login" -> #btn_login' in result["tree"]
    # Package prefix must not leak into the compact view.
    assert "com.example:id" not in result["tree"]


def test_compact_emits_actionable_roles_and_skips_layout() -> None:
    xml = (
        "<hierarchy>"
        '<node class="android.widget.FrameLayout" resource-id="pkg:id/container" text="" />'
        '<node class="android.widget.Button" resource-id="pkg:id/send" text="送信" clickable="true" />'
        '<node class="android.widget.EditText" resource-id="pkg:id/msg" text="" />'
        '<node class="android.widget.Switch" resource-id="pkg:id/notif" text="通知" checkable="true" checked="true" />'
        "</hierarchy>"
    )
    out = _xml_to_compact(xml)

    assert '[button] "送信" -> #send' in out
    assert "[input] -> #msg" in out
    assert '[toggle:on] "通知" -> #notif' in out
    # Pure layout container with no text/interactivity is dropped.
    assert "container" not in out


def test_compact_truncates_long_text() -> None:
    long_text = "あ" * 200
    xml = f'<hierarchy><node class="android.widget.TextView" text="{long_text}" /></hierarchy>'
    out = _xml_to_compact(xml)

    assert "…" in out
    assert len(out) < 120


def test_get_ui_tree_summary(ui_context) -> None:
    result = get_ui_tree(context=ui_context, format="summary")

    assert result["format"] == "summary"
    assert "id=com.example:id/btn_login | text=Login" in result["tree"]


def test_get_ui_tree_json(ui_context) -> None:
    result = get_ui_tree(context=ui_context, format="json")

    assert result["format"] == "json"
    assert result["tree"]["tag"] == "hierarchy"


def test_interact_and_observe_click_returns_markdown(ui_context) -> None:
    result = interact_and_observe(context=ui_context, action="click", selector="btn_login")

    assert "text" in result
    assert "Action Result" in result["text"]
    assert "UI Diff" in result["text"]
    assert "Logcat Snippet" in result["text"]
    assert "Success" in result["text"]


def test_interact_and_observe_input_requires_elicitation(ui_context) -> None:
    result = interact_and_observe(context=ui_context, action="input", selector="input_email", value=None)

    assert result["status"] == "requires_elicitation"
    assert "prompt" in result
    assert result["context_id"] == "input:input_email"


def test_interact_and_observe_reports_selector_failure(ui_context) -> None:
    result = interact_and_observe(context=ui_context, action="click", selector="missing_selector")

    assert "Failure" in result["text"]
    assert "ElementNotFound" in result["text"]
