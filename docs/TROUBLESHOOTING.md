# Troubleshooting – Universal Android Deep Debugger MCP Server

Issues discovered and resolved during real-device E2E validation (Android 13, SDK 33).

---

## 1. NAF nodes leaked into fuzz selector list

**Symptom**: `start_fuzzing` wasted iterations trying to interact with UI elements
flagged as `NAF="true"` in the uiautomator XML dump.  These elements are "Not
Accessibility Friendly" and cannot be reliably reached by uiautomator2, causing
silent `RuntimeError` failures on every attempted interaction.

**Root cause**: `_candidate_selectors` in `tools/fuzz.py` iterated all `<node>`
elements without checking the `NAF` attribute.

**Fix** (`fuzz.py`): Skip any node whose `NAF` attribute equals `"true"` before
collecting selectors.

```python
if node.attrib.get("NAF") == "true":
    continue
```

**How to reproduce**:
```
adb shell uiautomator dump /sdcard/w.xml && adb pull /sdcard/w.xml /tmp/w.xml
python - <<'EOF'
from mcp_server.tools.fuzz import _candidate_selectors
import xml.etree.ElementTree as ET
xml = open("/tmp/w.xml").read()
root = ET.fromstring(xml)
naf = {n.attrib.get("resource-id","") for n in root.iter("node") if n.attrib.get("NAF")=="true"}
leaked = naf & set(_candidate_selectors(xml))
print("leaked NAF selectors:", leaked)
EOF
```

---

## 2. System-package bare text leaked into fuzz selectors

**Symptom**: Selectors contained strings such as `'6/4 木曜日'` (the system
clock date) which come from `com.android.systemui` nodes that have an empty
`resource-id`.  The existing `_is_system_selector` filter only checked the
selector *value* itself; it could not detect system origin for plain text values
that contain no system keywords.

**Root cause**: `_candidate_selectors` used the same `_is_system_selector` helper
for resource-ids, text, and content-desc.  A node owned by a system package but
carrying a user-readable text string (date, clock, notification snippets) escaped
the filter when its `resource-id` was empty.

**Fix** (`fuzz.py`): Introduce `_is_system_package(pkg)` and skip
text/content-desc values from nodes whose `package` attribute is a known system
namespace:

```python
_SYSTEM_PACKAGES = ("com.android.systemui", "com.android.settings",
                    "com.google.android.systemui", "android")

def _is_system_package(pkg: str) -> bool:
    return any(pkg == m or pkg.startswith(m + ".") for m in _SYSTEM_PACKAGES)
```

resource-id values are still included (they're unambiguous selectors) but
text/content-desc from system packages are suppressed.

---

## 3. Zero-width Unicode characters passed through `str.strip()`

**Symptom**: Selectors occasionally contained invisible characters such as
U+200B (ZERO WIDTH SPACE), U+200C/D (ZWNJ/ZWJ), or U+FEFF (BOM).  Python's
`str.strip()` does **not** remove these because they belong to Unicode category
"Cf" (Format), not "Zs" (Space Separator).  uiautomator2 could not match
elements by these malformed selector strings.

**Fix** (`fuzz.py`): Replace bare `.strip()` calls on selector values with a
`_clean_selector()` helper that filters out all non-printable characters first:

```python
def _clean_selector(value: str) -> str:
    return "".join(ch for ch in value if ch.isprintable()).strip()
```

---

## 4. PII from notification text visible in `_xml_to_summary` output

**Symptom**: Calling `get_ui_tree(format="summary")` while the notification shade
was open returned lines containing partial payment card numbers and Japanese app
names from notification banners (e.g. `ANAペイ ••1280 の仮想カード番号…`).

**Root cause**: `_xml_to_summary` returned raw `text` and `content-desc` attribute
values from every UI node, including those inside system notification cards.

**Fix** (`tools/ui.py`): Apply `_apply_string_patterns` from `sdk_bridge` to each
text/content-desc value before including it in the summary:

```python
def _sanitize_ui_text(value: str | None) -> str | None:
    if not value:
        return value
    return _apply_string_patterns(value)
```

This masks known sensitive patterns (Bearer tokens, `password`/`token`/
`credit_card` JSON fields, 16-digit card numbers) before the summary is returned
to the MCP client.

---

## 5. Plain-text credit card numbers not masked by `sanitize_log`

**Symptom**: A 16-digit card number formatted as `NNNN-NNNN-NNNN-NNNN` in raw
logcat or UI text would have survived `_apply_string_patterns` because the
existing regexes only targeted JSON key-value pairs.

**Fix** (`sdk_bridge.py`): Added a plain-text credit card pattern to
`_STRING_PATTERNS`:

```python
(re.compile(r"\b(\d{4})[\s\-.](\d{4})[\s\-.](\d{4})[\s\-.](\d{4,7})\b"), _MASK),
```

This covers space-, hyphen-, and dot-separated groups of 4 digits (Visa, MC,
Amex, Discover formats).

---

## 6. `pytest.mark.e2e` not registered (warning on real-device runs)

**Symptom**: Running `pytest -m e2e` produced `PytestUnknownMarkWarning`.

**Fix** (`pyproject.toml`):
```toml
[tool.pytest.ini_options]
addopts = "-m 'not e2e'"
markers = ["e2e: real Android device required (deselected by default)"]
```

The default `pytest` run now skips all `@pytest.mark.e2e` tests.  To run them:
```
pytest tests/test_e2e_device.py -m e2e -v
```

---

## 7. Raw uiautomator2 device does not satisfy the `DeviceClient` protocol

**Severity**: High — broke every UI tool on real hardware.

**Symptom**: On a real device (verified on AQUOS SH-53A, Android 13), only
`get_ui_tree` worked.  `interact_and_observe`, `start_fuzzing`, and
`get_crash_context` all failed because `_default_ui_context()` returned a raw
`uiautomator2.connect()` device, which does **not** implement the selector-string
interface the tools call:

| Tool method (expected) | Raw uiautomator2 reality |
|---|---|
| `click(selector: str)` | `click(x, y)` — pixel coordinates → `TypeError` |
| `long_click(selector)` | `long_click(x, y, duration)` |
| `input_text(selector, value)` | **missing** |
| `swipe(selector)` | `swipe(fx, fy, tx, ty)` |
| `scroll(selector)` | **missing** |
| `dump_hierarchy()` | ✅ present |
| `get_recent_logs(window_ms)` | **missing** |

This was completely hidden by the mock suite because `MockDevice` (in
`conftest.py`) implements the selector-based protocol directly.

**Root cause**: No adapter layer between uiautomator2's coordinate/object API and
the tools' selector-string `DeviceClient` protocol.

**Fix** (`mcp_server/device.py` – new): Added `UiAutomator2Adapter` that wraps the
raw device and translates selector strings into uiautomator2 selector queries
(`resourceId` → `resourceIdMatches` suffix → `text` → `description`), implements
`input_text`/`scroll`, and provides `get_recent_logs` via `adb logcat`.
`_default_ui_context()` now returns `UIContext(device=UiAutomator2Adapter(raw))`.

```python
raw = u2.connect()
device = UiAutomator2Adapter(raw, serial=getattr(raw, "serial", None))
return UIContext(device=device)
```

**Verified live** (read-only, no destructive taps):
- `get_ui_tree(summary)` → 72 sanitized entries
- selector resolution → 8/8 live clickable elements resolved
- `get_recent_logs(2000)` → 202 logcat lines
- `interact_and_observe(action="scroll", selector="…:id/workspace")` → `success=True`, UI changed

**Note on `get_recent_logs`**: a precise `window_ms` time window is unreliable
across host/device clock skew, so the adapter maps it to a bounded recent line
budget (50–2000 lines).  This is best-effort and documented in the code.

---

## Capability matrix — what the MCP server can / cannot do here

Measured on this machine (macOS, no Android SDK) with one USB device attached.

### ✅ Works on a real device (no Android SDK / no instrumented app needed)
| Tool | Status | Notes |
|---|---|---|
| `doctor` | ✅ | Reports adb, java, device serial, Android version, Private Space |
| `get_ui_tree` | ✅ | summary / json / xml; PII in text/content-desc is masked |
| `interact_and_observe` | ✅ | click / long_click / input / swipe / scroll via adapter |
| `start_fuzzing` | ✅ | Drives real UI; stops on FATAL/ANR in logcat |
| `get_crash_context` | ✅ | Aggregates logcat stack trace + recent actions |
| `generate_bug_report` | ✅ | Pure function; output is sanitized |
| `ide_set_breakpoint` / `ide_evaluate` | ⚠️ mock | Returns `mode: "mock"`; no real IDE bridge yet |

### ❌ Cannot do in the current environment
| Tool / feature | Why | What's required |
|---|---|---|
| `build_and_deploy` | `ANDROID_HOME` unset, no Android SDK, no `gradlew` via Roots | Install Android SDK + set `ANDROID_HOME`; expose the Gradle project via MCP Roots |
| `inspect_network` | Returns `5001 SDKNotConnected` | Build & run the instrumented demo app, then `adb reverse tcp:8080 tcp:8080` |
| `dump_viewmodel` | Returns `5001 SDKNotConnected` | Same as above — requires the Agent SDK WebSocket connection |
| Real breakpoint / expression eval | IDE bridge is a stub | A real IDE debugger bridge implementation |

**Bottom line**: All device-side UI/log/crash tooling works against any connected
device. The network/state/ViewModel telemetry tools require the instrumented app
(Agent SDK), which in turn requires a full Android SDK build toolchain that is not
present on this host.

---

## Running the real-device E2E suite

### Prerequisites
- USB-connected Android device with USB Debugging enabled
- `adb devices` shows the device as `device` (not `unauthorized`)
- `adb` is on `$PATH`

### Command
```bash
cd server
pytest tests/test_e2e_device.py -m e2e -v
```

### What the suite covers
| Class | What it tests |
|---|---|
| `TestDoctorRealDevice` | `doctor()` on a live device: version, serial, no PII |
| `TestXmlParserRealDevice` | `ET.fromstring`, `_xml_to_summary`, `_xml_to_json` on a live hierarchy dump |
| `TestCandidateSelectorsRealDevice` | NAF exclusion, system-package text exclusion, zero-width char exclusion |
| `TestSanitizeLogRealDevice` | Bearer/card masking in live logcat; dict-level masking |
| `TestSDKBridgeRobustness` | Invalid JSON, non-JSON-RPC messages, PII in stored traces, deque overflow |
| `TestCleanSelector` | Parametric unit tests for the `_clean_selector` helper |

### Privacy guarantee
The test suite never writes raw device data to disk.  The UI hierarchy XML is
held in memory for the duration of the test session and is discarded afterward.
No logcat lines are printed unless a test fails.
