"""Tests for :mod:`mcp_server.tools.state` (dump_viewmodel tool)."""
from __future__ import annotations

import pytest

from mcp_server.tools.state import StateContext, dump_viewmodel
from tests.conftest import MockStateGateway


def test_dump_viewmodel_returns_all_states(state_context: StateContext) -> None:
    result = dump_viewmodel(state_context)

    assert result["sdk_connected"] is True
    assert result["count"] == 1
    assert "LoginViewModel" in result["states"]


def test_dump_viewmodel_state_structure(state_context: StateContext) -> None:
    result = dump_viewmodel(state_context)
    vm_state = result["states"]["LoginViewModel"]

    assert vm_state["isLoading"] is False
    assert vm_state["error"] is None
    assert vm_state["user"]["name"] == "Admin"


def test_dump_viewmodel_filtered_by_class(state_context: StateContext) -> None:
    result = dump_viewmodel(state_context, class_name="LoginViewModel")

    assert result["sdk_connected"] is True
    assert result["count"] == 1
    assert "LoginViewModel" in result["states"]
    assert result["class_name_filter"] == "LoginViewModel"


def test_dump_viewmodel_filter_not_found() -> None:
    context = StateContext(
        gateway=MockStateGateway(
            connected=True,
            states={"LoginViewModel": {"isLoading": False}},
        )
    )
    result = dump_viewmodel(context, class_name="HomeViewModel")

    assert result["sdk_connected"] is True
    assert result["count"] == 0
    assert result["states"] == {}
    assert "warning" in result
    assert "HomeViewModel" in result["warning"]


def test_dump_viewmodel_sdk_not_connected() -> None:
    context = StateContext(gateway=MockStateGateway(connected=False))
    result = dump_viewmodel(context)

    assert result["sdk_connected"] is False
    assert "warning" in result
    assert "SDKNotConnected" in result["warning"]
    assert result["states"] == {}


def test_dump_viewmodel_multiple_viewmodels() -> None:
    context = StateContext(
        gateway=MockStateGateway(
            connected=True,
            states={
                "LoginViewModel": {"isLoading": False},
                "HomeViewModel": {"feed": []},
                "ProfileViewModel": {"name": "Alice"},
            },
        )
    )
    result = dump_viewmodel(context)

    assert result["count"] == 3
    assert "LoginViewModel" in result["states"]
    assert "HomeViewModel" in result["states"]
    assert "ProfileViewModel" in result["states"]


def test_dump_viewmodel_empty_states() -> None:
    context = StateContext(gateway=MockStateGateway(connected=True, states={}))
    result = dump_viewmodel(context)

    assert result["sdk_connected"] is True
    assert result["count"] == 0
    assert result["states"] == {}
