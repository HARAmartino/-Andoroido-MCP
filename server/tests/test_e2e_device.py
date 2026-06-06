"""Real-device E2E tests.

Run only when a physical Android device is attached via USB:

    pytest tests/test_e2e_device.py -m e2e -v

These tests are intentionally excluded from the standard CI pytest run because
they require a live ``adb`` connection.  All sensitive data collected from the
device is kept in-process and never written to disk or logged verbatim.
"""
from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET

import pytest

from mcp_server.sdk_bridge import SDKBridge, sanitize_log, _apply_string_patterns
from mcp_server.tools.fuzz import _candidate_selectors, _is_system_selector, _is_system_package, _clean_selector
from mcp_server.tools.system import DoctorContext, SubprocessAdb, doctor
from mcp_server.tools.ui import _xml_to_summary, _xml_to_json


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _first_device_serial() -> str | None:
    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        if "\tdevice" in line:
            return line.split("\t", maxsplit=1)[0].strip()
    return None


_DEVICE_SERIAL = _first_device_serial()
_HAVE_DEVICE = _DEVICE_SERIAL is not None

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def device_serial() -> str:
    if not _HAVE_DEVICE:
        pytest.skip("no real Android device connected via adb")
    assert _DEVICE_SERIAL is not None
    return _DEVICE_SERIAL


@pytest.fixture(scope="session")
def real_xml(device_serial: str) -> str:
    """Dump the live UI hierarchy from the connected device."""
    subprocess.run(
        ["adb", "-s", device_serial, "shell", "uiautomator", "dump", "/sdcard/window_dump.xml"],
        check=True, capture_output=True, text=True,
    )
    raw = subprocess.run(
        ["adb", "-s", device_serial, "shell", "cat", "/sdcard/window_dump.xml"],
        check=True, capture_output=True, text=True,
    ).stdout
    return raw


@pytest.fixture(scope="session")
def real_logcat(device_serial: str) -> list[str]:
    """Capture a short logcat snapshot (100 most recent lines)."""
    out = subprocess.run(
        ["adb", "-s", device_serial, "shell", "logcat", "-d", "-t", "100"],
        capture_output=True, text=True, timeout=15,
    ).stdout
    return out.splitlines()


# ---------------------------------------------------------------------------
# E2E: doctor() on real device
# ---------------------------------------------------------------------------

class TestDoctorRealDevice:
    def test_doctor_reports_connected_device(self, device_serial: str) -> None:
        ctx = DoctorContext(adb=SubprocessAdb())
        report = doctor(ctx)
        assert "✅" in report, "doctor() should show at least one green check"
        assert device_serial in report, "doctor() should mention the connected serial"

    def test_doctor_contains_android_version(self, device_serial: str) -> None:
        ctx = DoctorContext(adb=SubprocessAdb())
        report = doctor(ctx)
        assert "android version" in report.lower()
        assert "SDK" in report

    def test_doctor_no_pii_leak(self, device_serial: str) -> None:
        ctx = DoctorContext(adb=SubprocessAdb())
        report = doctor(ctx)
        # Device serial is not PII, but passwords / tokens must not appear
        assert '"password"' not in report
        assert "Bearer " not in report or "***MASKED***" in report


# ---------------------------------------------------------------------------
# E2E: XML parsing on real hierarchy
# ---------------------------------------------------------------------------

class TestXmlParserRealDevice:
    def test_fromstring_succeeds(self, real_xml: str) -> None:
        root = ET.fromstring(real_xml)
        assert root is not None

    def test_summary_returns_string(self, real_xml: str) -> None:
        summary = _xml_to_summary(real_xml)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_summary_no_raw_card_numbers(self, real_xml: str) -> None:
        summary = _xml_to_summary(real_xml)
        # A bare 16-digit card number should be masked
        raw_card = re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")
        assert not raw_card.search(summary), (
            "Unmasked card number found in UI summary"
        )

    def test_json_tree_is_dict(self, real_xml: str) -> None:
        tree = _xml_to_json(real_xml)
        assert isinstance(tree, dict)
        assert "tag" in tree
        assert "children" in tree

    def test_naf_attribute_does_not_crash_parser(self, real_xml: str) -> None:
        root = ET.fromstring(real_xml)
        naf_count = sum(1 for n in root.iter("node") if n.attrib.get("NAF") == "true")
        # Real devices typically have NAF nodes; parsing must succeed regardless
        assert naf_count >= 0  # always true – just confirms no exception above


# ---------------------------------------------------------------------------
# E2E: _candidate_selectors on real XML
# ---------------------------------------------------------------------------

class TestCandidateSelectorsRealDevice:
    def test_naf_nodes_excluded(self, real_xml: str) -> None:
        root = ET.fromstring(real_xml)
        naf_rids = {
            n.attrib.get("resource-id", "").strip()
            for n in root.iter("node")
            if n.attrib.get("NAF") == "true"
               and n.attrib.get("resource-id", "").strip()
        }
        selectors = set(_candidate_selectors(real_xml))
        leaked = naf_rids & selectors
        assert not leaked, f"NAF resource-ids leaked into selectors: {leaked}"

    def test_system_package_bare_text_excluded(self, real_xml: str) -> None:
        root = ET.fromstring(real_xml)
        system_bare_texts: set[str] = set()
        for n in root.iter("node"):
            pkg = n.attrib.get("package", "")
            if not _is_system_package(pkg):
                continue
            rid = n.attrib.get("resource-id", "").strip()
            if rid:
                continue  # has its own resource-id – filtered elsewhere
            for key in ("text", "content-desc"):
                val = n.attrib.get(key, "").strip()
                if val and not _is_system_selector(val):
                    system_bare_texts.add(val)

        selectors = set(_candidate_selectors(real_xml))
        leaked = system_bare_texts & selectors
        assert not leaked, (
            f"System-package bare text leaked into selectors: {list(leaked)[:5]}"
        )

    def test_no_zero_width_chars_in_selectors(self, real_xml: str) -> None:
        zero_width = {"​", "‌", "‍", "﻿"}
        for sel in _candidate_selectors(real_xml):
            bad = zero_width & set(sel)
            assert not bad, f"Zero-width char in selector: {repr(sel)}"

    def test_selectors_list_is_reasonable(self, real_xml: str) -> None:
        selectors = _candidate_selectors(real_xml)
        # Should produce some selectors (screen is not blank) but not an explosion
        assert len(selectors) >= 0  # screen might be blank in some states
        assert len(selectors) < 5000, "Selector explosion – parser bug?"


# ---------------------------------------------------------------------------
# E2E: sanitize_log on real logcat lines
# ---------------------------------------------------------------------------

class TestSanitizeLogRealDevice:
    def test_no_raw_bearer_tokens_in_sanitized_logcat(self, real_logcat: list[str]) -> None:
        for line in real_logcat:
            sanitized = _apply_string_patterns(line)
            if re.search(r"Authorization:\s*Bearer\s+", line, re.IGNORECASE):
                assert "***MASKED***" in sanitized, (
                    f"Unmasked Bearer token in logcat line: {repr(sanitized[:120])}"
                )

    def test_no_raw_card_numbers_in_sanitized_logcat(self, real_logcat: list[str]) -> None:
        raw_card = re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")
        for line in real_logcat:
            if raw_card.search(line):
                sanitized = _apply_string_patterns(line)
                assert not raw_card.search(sanitized), (
                    f"Unmasked card number after sanitization: {repr(sanitized[:120])}"
                )

    def test_sanitize_log_dict_masks_known_keys(self) -> None:
        payload = {
            "user": "alice",
            "password": "s3cr3t!",
            "token": "tok_abc123",
            "credit_card": "4111-1111-1111-1111",
            "nested": {"token": "inner_token"},
        }
        result = sanitize_log(payload)
        assert result["password"] == "***MASKED***"
        assert result["token"] == "***MASKED***"
        assert result["credit_card"] == "***MASKED***"
        assert result["nested"]["token"] == "***MASKED***"
        assert result["user"] == "alice"


# ---------------------------------------------------------------------------
# E2E: SDKBridge message handling (in-process, no real SDK required)
# ---------------------------------------------------------------------------

class TestSDKBridgeRobustness:
    def test_handle_message_invalid_json(self) -> None:
        b = SDKBridge()
        b.handle_message("not json at all {{{")
        # Must not raise; bridge silently ignores bad JSON

    def test_handle_message_non_jsonrpc(self) -> None:
        b = SDKBridge()
        b.handle_message('{"method": "telemetry/network", "params": {}}')
        # jsonrpc field absent → ignored silently

    def test_handle_message_sanitizes_before_storing(self) -> None:
        b = SDKBridge()
        msg = (
            '{"jsonrpc":"2.0","method":"telemetry/network","params":{'
            '"request":{"url":"https://example.com","method":"POST",'
            '"headers":{"Authorization":"Bearer secret_token_xyz"}},'
            '"response":{"status":200}}}'
        )
        b.handle_message(msg)
        traces = b.get_network_traces()
        assert traces, "Trace should have been stored"
        auth_header = traces[0].get("request", {}).get("headers", {}).get("Authorization", "")
        assert "secret_token_xyz" not in auth_header, (
            "Raw Bearer token leaked into stored network trace"
        )
        assert "***MASKED***" in auth_header

    def test_handle_message_network_with_password(self) -> None:
        b = SDKBridge()
        b._connected = True
        msg = (
            '{"jsonrpc":"2.0","method":"telemetry/network","params":{'
            '"request":{"url":"https://api.example.com/login","method":"POST",'
            '"body":{"username":"user","password":"my_secret"}},'
            '"response":{"status":200,"body":{"token":"jwt_abc"}}}}'
        )
        b.handle_message(msg)
        traces = b.get_network_traces()
        body = traces[0].get("request", {}).get("body", {})
        assert body.get("password") == "***MASKED***"
        resp_body = traces[0].get("response", {}).get("body", {})
        assert resp_body.get("token") == "***MASKED***"

    def test_handle_message_large_burst_no_overflow(self) -> None:
        b = SDKBridge()
        for i in range(600):  # exceeds MAX_NETWORK_TRACES (500)
            b.handle_message(
                f'{{"jsonrpc":"2.0","method":"telemetry/network","params":{{"seq":{i}}}}}'
            )
        traces = b.get_network_traces()
        assert len(traces) <= 500, "Deque should cap at MAX_NETWORK_TRACES"
        # Most recent should be at the end
        assert traces[-1].get("seq") == 599


# ---------------------------------------------------------------------------
# E2E: _clean_selector behaviour
# ---------------------------------------------------------------------------

class TestCleanSelector:
    @pytest.mark.parametrize("raw,expected", [
        ("normal text", "normal text"),
        ("​Hidden​", "Hidden"),          # zero-width space stripped
        ("﻿BOM marker", "BOM marker"),         # BOM stripped
        ("  spaced  ", "spaced"),                   # ASCII whitespace stripped
        ("‌‍Invisible", "Invisible"),     # ZWNJ / ZWJ stripped
        ("", ""),
    ])
    def test_clean_selector_strips_nonprintable(self, raw: str, expected: str) -> None:
        assert _clean_selector(raw) == expected
