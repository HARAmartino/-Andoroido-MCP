from __future__ import annotations

from mcp_server.tools.report import generate_bug_report


def test_generate_bug_report_includes_sections_and_sanitizes() -> None:
    result = generate_bug_report(
        title="Crash on Login",
        steps=["Open app", "Tap Login"],
        crash_context={"stack_trace": ['"password":"abc.def.ghi"', "Authorization: ******"]},
        logs=["Authorization: ******", '{"password":"letmein"}'],
        network_traces=[
            {
                "request": {"headers": {"Authorization": "raw-secret-token"}},
                "response": {"body": {"token": "token-123"}},
            }
        ],
        screenshot_base64="ZmFrZS1iYXNlNjQ=",
    )

    text = result["text"]
    assert "# Crash on Login" in text
    assert "## Reproduction Steps" in text
    assert "## Network Traces" in text
    assert "## Screenshot" in text
    assert "***MASKED***" in text
    assert "letmein" not in text
    assert "token-123" not in text
    assert "abc.def.ghi" not in text
    assert "raw-secret-token" not in text
