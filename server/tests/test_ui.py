from __future__ import annotations

from mcp_server.tools.ui import get_ui_tree, interact_and_observe


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
