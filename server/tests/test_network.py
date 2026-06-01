"""Tests for :mod:`mcp_server.tools.network` (inspect_network tool)."""
from __future__ import annotations

import pytest

from mcp_server.tools.network import NetworkContext, inspect_network
from tests.conftest import MockNetworkGateway


def test_inspect_network_returns_traces(network_context: NetworkContext) -> None:
    result = inspect_network(network_context)

    assert result["sdk_connected"] is True
    assert result["count"] == 1
    assert len(result["traces"]) == 1


def test_inspect_network_trace_structure(network_context: NetworkContext) -> None:
    result = inspect_network(network_context)
    trace = result["traces"][0]

    assert "request" in trace
    assert "response" in trace
    assert trace["request"]["method"] == "POST"
    assert trace["request"]["url"] == "https://api.example.com/login"


def test_inspect_network_filter_by_url(network_context: NetworkContext) -> None:
    result = inspect_network(network_context, filter="login")

    assert result["count"] == 1
    assert result["filter"] == "login"


def test_inspect_network_filter_no_match(network_context: NetworkContext) -> None:
    result = inspect_network(network_context, filter="nonexistent_endpoint")

    assert result["count"] == 0
    assert result["traces"] == []


def test_inspect_network_filter_by_method(network_context: NetworkContext) -> None:
    result_post = inspect_network(network_context, filter="POST")
    result_get = inspect_network(network_context, filter="GET")

    assert result_post["count"] == 1
    assert result_get["count"] == 0


def test_inspect_network_sdk_not_connected() -> None:
    context = NetworkContext(gateway=MockNetworkGateway(connected=False))
    result = inspect_network(context)

    assert result["sdk_connected"] is False
    assert "warning" in result
    assert "SDKNotConnected" in result["warning"]
    assert result["traces"] == []


def test_inspect_network_empty_when_no_traces() -> None:
    context = NetworkContext(gateway=MockNetworkGateway(connected=True, traces=[]))
    result = inspect_network(context)

    assert result["sdk_connected"] is True
    assert result["count"] == 0
    assert result["traces"] == []


def test_inspect_network_no_filter_returns_all() -> None:
    traces = [
        {"request": {"method": "GET", "url": "https://api.example.com/users"}, "response": {}, "latency_ms": 50},
        {"request": {"method": "POST", "url": "https://api.example.com/login"}, "response": {}, "latency_ms": 120},
    ]
    context = NetworkContext(gateway=MockNetworkGateway(connected=True, traces=traces))
    result = inspect_network(context)

    assert result["count"] == 2
