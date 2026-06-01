from __future__ import annotations

import pytest

from mcp_server.main import runtime


@pytest.mark.asyncio
async def test_sampling_hook_truncates_large_payload() -> None:
    large = "x" * 4500
    summary = await runtime.summarize_large_payload(large, max_chars=100)

    assert len(summary) <= 100
    assert "truncated" in summary
