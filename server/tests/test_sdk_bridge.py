"""Tests for :mod:`mcp_server.sdk_bridge`."""
from __future__ import annotations

import json

import pytest

from mcp_server.sdk_bridge import SDKBridge, sanitize_log, _MASK


# ---------------------------------------------------------------------------
# sanitize_log unit tests
# ---------------------------------------------------------------------------

class TestSanitizeLog:
    def test_masks_password_in_dict(self) -> None:
        data = {"username": "admin", "password": "secret123"}
        result = sanitize_log(data)
        assert result["password"] == _MASK
        assert result["username"] == "admin"

    def test_masks_token_in_dict(self) -> None:
        data = {"token": "mytoken123"}
        result = sanitize_log(data)
        assert result["token"] == _MASK

    def test_masks_credit_card_in_dict(self) -> None:
        data = {"credit_card": "4111111111111111"}
        result = sanitize_log(data)
        assert result["credit_card"] == _MASK

    def test_masks_authorization_header(self) -> None:
        data = {"headers": {"Authorization": "some-auth-value"}}
        result = sanitize_log(data)
        assert result["headers"]["Authorization"] == _MASK

    def test_leaves_safe_fields_unchanged(self) -> None:
        data = {"url": "https://api.example.com", "status": 200}
        result = sanitize_log(data)
        assert result == data

    def test_handles_nested_dict(self) -> None:
        data = {"request": {"body": {"password": "p@ssw0rd"}, "url": "https://x.com"}}
        result = sanitize_log(data)
        assert result["request"]["body"]["password"] == _MASK
        assert result["request"]["url"] == "https://x.com"

    def test_handles_list(self) -> None:
        data = [{"password": "s3cr3t"}, {"token": "tok"}]
        result = sanitize_log(data)
        assert result[0]["password"] == _MASK
        assert result[1]["token"] == _MASK

    def test_handles_string_with_password_json(self) -> None:
        raw = '{"password": "hunter2"}'
        result = sanitize_log(raw)
        assert "hunter2" not in result
        assert _MASK in result

    def test_non_string_values_not_masked(self) -> None:
        data = {"count": 42, "active": True, "items": None}
        result = sanitize_log(data)
        assert result == data

    def test_masks_token_in_string(self) -> None:
        raw = '{"token": "abc123"}'
        result = sanitize_log(raw)
        assert "abc123" not in result
        assert _MASK in result


# ---------------------------------------------------------------------------
# SDKBridge.handle_message routing tests
# ---------------------------------------------------------------------------

class TestSDKBridgeHandleMessage:
    def _make_bridge(self) -> SDKBridge:
        return SDKBridge()

    def _network_msg(self, url: str = "https://api.example.com/login", password: str = "secret") -> str:
        return json.dumps({
            "jsonrpc": "2.0",
            "method": "telemetry/network",
            "params": {
                "timestamp": 1717123456789,
                "request": {
                    "method": "POST",
                    "url": url,
                    "headers": {"Authorization": "some-auth-value"},
                    "body": {"password": password},
                },
                "response": {"status": 200, "body": {"token": "eyJ..."}},
                "latency_ms": 100,
            },
        })

    def _state_msg(self, vm: str = "LoginViewModel") -> str:
        return json.dumps({
            "jsonrpc": "2.0",
            "method": "telemetry/state",
            "params": {
                "viewmodel": vm,
                "state": {"isLoading": False, "user": {"id": 1}},
            },
        })

    def test_network_message_stored(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._network_msg())
        traces = bridge.get_network_traces()
        assert len(traces) == 1

    def test_network_message_sanitized_auth_header(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._network_msg())
        trace = bridge.get_network_traces()[0]
        auth = trace["request"]["headers"]["Authorization"]
        assert auth == _MASK

    def test_network_message_sanitized_password(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._network_msg())
        trace = bridge.get_network_traces()[0]
        assert trace["request"]["body"]["password"] == _MASK

    def test_network_message_sanitized_response_token(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._network_msg())
        trace = bridge.get_network_traces()[0]
        assert trace["response"]["body"]["token"] == _MASK

    def test_state_message_stored(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._state_msg())
        states = bridge.get_viewmodel_states()
        assert "LoginViewModel" in states

    def test_state_message_filtered_by_class(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._state_msg("LoginViewModel"))
        bridge.handle_message(self._state_msg("HomeViewModel"))
        result = bridge.get_viewmodel_states(class_name="LoginViewModel")
        assert "LoginViewModel" in result
        assert "HomeViewModel" not in result

    def test_network_filter_by_url(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._network_msg(url="https://api.example.com/login"))
        bridge.handle_message(self._network_msg(url="https://api.example.com/profile"))
        traces = bridge.get_network_traces(filter="login")
        assert len(traces) == 1

    def test_network_filter_by_method(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(self._network_msg())
        traces = bridge.get_network_traces(filter="POST")
        assert len(traces) == 1
        traces_get = bridge.get_network_traces(filter="GET")
        assert len(traces_get) == 0

    def test_invalid_json_ignored(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message("not valid json {{")
        assert bridge.get_network_traces() == []

    def test_non_jsonrpc_message_ignored(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(json.dumps({"method": "telemetry/network", "params": {}}))
        assert bridge.get_network_traces() == []

    def test_multiple_network_messages_accumulate(self) -> None:
        bridge = self._make_bridge()
        for i in range(5):
            bridge.handle_message(self._network_msg(url=f"https://api.example.com/{i}"))
        assert len(bridge.get_network_traces()) == 5

    def test_state_updated_on_duplicate_viewmodel(self) -> None:
        bridge = self._make_bridge()
        bridge.handle_message(json.dumps({
            "jsonrpc": "2.0",
            "method": "telemetry/state",
            "params": {"viewmodel": "VM", "state": {"count": 1}},
        }))
        bridge.handle_message(json.dumps({
            "jsonrpc": "2.0",
            "method": "telemetry/state",
            "params": {"viewmodel": "VM", "state": {"count": 2}},
        }))
        assert bridge.get_viewmodel_states()["VM"]["count"] == 2
