# 📘 Technical Specification: Universal Android Deep Debugger MCP Server
**Document Version**: 1.1 (Final / Autonomous Loop Ready)
**Protocol Version**: Model Context Protocol (MCP) **2025-11-25**
**Target Audience**: AI Agents (Codex, Claude Code, Cline), MCP Client Developers, Android Tooling Engineers

---

## 1. Overview
This document defines the technical interface for the **Universal Android Deep Debugger MCP Server**. It enables AI agents to control Android devices, inspect internal application states (ViewModel, Network, DB), and manage build pipelines via the **Model Context Protocol (MCP)**.

### 1.1 Architecture
The system operates as a bridge between the Host PC (Development Environment) and the Android Device (Target).

```mermaid
graph TD
    Client[AI Agent / MCP Client] <-->|JSON-RPC (MCP)| Server[MCP Server (Python)]
    
    subgraph "Host PC"
        Server <-->|Roots API| FS[Project Filesystem]
        Server <-->|Subprocess| Gradle[Build System]
        Server <-->|WebSocket| Gateway[SDK Gateway]
        Server <-->|JDWP/Plugin| IDE[Android Studio]
    end
    
    subgraph "Android Device"
        OS[Android OS 15+] <-->|ADB| Server
        App[Target App] <-->|Hook| SDK[Agent SDK]
        SDK <-->|WebSocket (adb reverse)| Gateway
    end
```

---

## 2. MCP Capabilities & Protocol Features

### 2.1 Roots (Workspace Awareness)
The server utilizes the **Roots** feature to dynamically locate the Android project structure (e.g., `gradlew`, `AndroidManifest.xml`) without hardcoded paths.
*   **Usage**: Upon initialization, the server requests `roots/list` from the client.
*   **Logic**: It identifies the root directory containing `build.gradle.kts` or `gradlew` to execute build commands correctly.

### 2.2 Sampling (LLM-Assisted Summarization)
To manage context window limits, the server uses **Sampling** (`sampling/createMessage`) to request the client's LLM to summarize large payloads (e.g., raw Logcat, massive UI XMLs) before returning them to the agent.
*   **Trigger**: When a tool output exceeds ~4000 tokens.
*   **Flow**: Server sends `sampling/createMessage` with prompt: *"Summarize this Android Logcat trace, focusing on FATAL EXCEPTION and network errors."* -> Client returns summary -> Server returns summary to Agent.

### 2.3 Elicitation (Human-in-the-Loop)
Since MCP servers run as background processes (stdio/daemon) and cannot render GUI dialogs, this server implements Elicitation via an **"Interrupt & Resume"** pattern.
*   **Mechanism**: When sensitive input (e.g., 2FA, Password) is required, the tool does **not** block. Instead, it returns a structured JSON response with `status: "requires_elicitation"` and a `prompt` message.
*   **Agent Workflow**:
    1.  Agent receives `requires_elicitation` response.
    2.  Agent asks the user for the input via the chat interface (e.g., "I need the 2FA code to proceed.").
    3.  Agent re-invokes the tool, passing the user's input into the `context` or `auth_code` parameter.
*   **Benefit**: Works universally across CLI (Codex), IDE (Cursor), and Chat (Claude Desktop) clients without GUI dependencies.

---

## 3. Tools Specification

### 3.1 Core Control Tools

#### `doctor`
Diagnoses the development environment.
*   **Input**: `None`
*   **Output**: Markdown Report
    *   Checks: `ANDROID_HOME`, `adb` version, `java` version, `gradlew` presence (via Roots), Device connection status.
    *   **Android 15 Check**: Verifies if connected device is running Android 15+ and warns about Private Space restrictions.

#### `build_and_deploy`
Builds the app and installs it on the target device.
*   **Input**:
    *   `clean` (boolean, default: false): Run `clean` task before build.
    *   `variant` (string, default: "debug"): Build variant.
*   **Logic**:
    1.  Resolve project root via **Roots**.
    2.  Execute `./gradlew assemble<Variant>`.
    3.  **Android 15 Private Space Handling**:
        *   Detect if the target package is in a Private Space profile (User ID $\ge$ 10).
        *   If detected, append `--user <userId>` to `adb install` command.
*   **Output**: Build logs + Installation status.

#### `interact_and_observe`
**Compound Tool**: Performs a UI action and returns the immediate aftermath (UI State + Logs).
*   **Input**:
    *   `action` (enum: "click", "long_click", "input", "swipe", "scroll")
    *   `selector` (string): Resource ID, Text, or Description (e.g., `"@+id/btn_login"`, `"Login"`). **Coordinates are discouraged.**
    *   `value` (string, optional): Text input value.
*   **Output**:
    *   `text`: Markdown report containing:
        1.  **Action Result**: Success/Failure.
        2.  **UI Diff**: Summary of changed elements (e.g., "New Dialog appeared", "EditText updated").
        3.  **Logcat Snippet**: Logs generated within 500ms of the action.

#### `get_ui_tree`
Retrieves the Accessibility Tree (UI Hierarchy).
*   **Input**:
    *   `format` (enum: "json", "xml", "summary"): Default is "summary" (token-optimized).
*   **Output**: Structured representation of the current screen.

### 3.2 Deep Inspection Tools (SDK Required)

#### `inspect_network`
Retrieves recent HTTP traffic intercepted by the Agent SDK.
*   **Input**: `filter` (string, optional): URL or Method filter.
*   **Output**: JSON Array of `NetworkTrace` objects.
    *   *Security*: Headers like `Authorization` and bodies containing `password` are automatically masked (`***MASKED***`).

#### `dump_viewmodel`
Dumps the internal state of active ViewModels.
*   **Input**: `class_name` (string, optional): Specific ViewModel to dump.
*   **Output**: JSON Object representing `StateFlow` / `LiveData` values.

#### `query_internal_db`
Executes SQL against the app's internal SQLite/Room database.
*   **Input**: `sql` (string).
*   **Constraint**: Only works if `debuggable="true"`. Uses `run-as <package>` under the hood.
*   **Output**: JSON/CSV ResultSet.

### 3.3 Advanced Debugging (Autonomous Loop)

#### `ide_set_breakpoint`
(Requires IDE Plugin) Sets a breakpoint in the IDE at the specified file/line. Crucial for "Reproduce -> Catch -> Inspect" loops.
*   **Input**:
    *   `file_path` (string): Relative path from project root.
    *   `line` (integer): Line number.
    *   `condition` (string, optional): Breakpoint condition (e.g., `user == null`).
*   **Output**: `text` (Breakpoint ID and confirmation).

#### `ide_evaluate`
(Requires IDE Plugin) Evaluates an expression in the attached debugger.
*   **Input**: `expression` (string, e.g., `userRepository.currentUser`).
*   **Output**: String representation of the evaluated value.
*   **Note**: Only works when the debugger is paused (e.g., hit a breakpoint set by `ide_set_breakpoint`).

#### `start_fuzzing`
Starts a randomized UI test (Monkey/Chaos).
*   **Input**: `duration_sec` (integer), `strategy` (enum: "random", "guided").
*   **Output**: Stream of crash logs or "Completed" status.

---

## 4. Resources Specification

Agents can subscribe to or read these URIs to maintain context.

| URI Scheme | Description | Content Type | Update Trigger |
| :--- | :--- | :--- | :--- |
| `android://device/info` | Device Model, OS Version, Battery, **Profile Type (Main/Private)**. | `application/json` | On Connect / Change |
| `android://screen/current` | Current UI Hierarchy (Pruned JSON). | `application/json` | Screen Change |
| `android://logs/live` | Real-time Logcat stream (Error/Warning filter). | `text/plain` (Stream) | Continuous |
| `project://structure` | Parsed `AndroidManifest.xml` & `build.gradle` dependencies. | `application/json` | On Build |
| `session://history` | List of executed tools and their outcomes (for replay). | `application/json` | On Tool Call |

---

## 5. Android Agent SDK Protocol (WebSocket)

The embedded SDK communicates with the MCP Server via WebSocket (tunneled through `adb reverse tcp:8080 tcp:8080`).

### 5.1 Message Format (JSON-RPC 2.0)

**Event: Network Trace**
```json
{
  "jsonrpc": "2.0",
  "method": "telemetry/network",
  "params": {
    "timestamp": 1717123456789,
    "request": {
      "method": "POST",
      "url": "https://api.example.com/login",
      "headers": { "Content-Type": "application/json" },
      "body": { "user": "admin", "password": "***MASKED***" }
    },
    "response": {
      "status": 200,
      "body": { "token": "eyJ..." }
    },
    "latency_ms": 450
  }
}
```

**Event: ViewModel State**
```json
{
  "jsonrpc": "2.0",
  "method": "telemetry/state",
  "params": {
    "viewmodel": "LoginViewModel",
    "state": {
      "isLoading": false,
      "error": null,
      "user": { "id": 1, "name": "Admin" }
    }
  }
}
```

### 5.2 Auto-Masking Rules
The SDK **must** apply the following regex replacements before sending data:
*   `Authorization: Bearer .*` -> `Authorization: Bearer ***MASKED***`
*   `"password":\s*".*?"` -> `"password": "***MASKED***"`
*   `"token":\s*".*?"` -> `"token": "***MASKED***"`
*   `"credit_card":\s*".*?"` -> `"credit_card": "***MASKED***"`

---

## 6. Android 15+ Compatibility Strategy

### 6.1 Private Space Detection
The `doctor` tool and `android://device/info` resource must detect if the target app is running in a **Private Space** (User ID $\ge$ 10).
*   **Detection Method**: `adb shell dumpsys user`.
*   **Implication**: Apps in Private Space are isolated. Standard `adb install` might fail or install to the wrong profile.
*   **Mitigation**:
    1.  The `build_and_deploy` tool will attempt to resolve the correct `userId` for the target package.
    2.  If the app is locked/unavailable, the tool returns a specific error code `ERR_PRIVATE_SPACE_LOCKED` and suggests the user to unlock the space via `elicit_input` or manual intervention.

### 6.2 Accessibility Permissions
Android 15 restricts Accessibility Services for sideloaded apps.
*   **Requirement**: The Agent SDK (if it uses Accessibility) or the `uiautomator2` daemon must be granted permissions via `adb shell pm grant ...` or `adb shell appops set ...`.
*   **Automation**: The `doctor` tool will verify these permissions and provide the exact `adb` commands to fix them if missing.

---

## 7. Error Handling

The server returns standard MCP Error objects with specific codes for Android issues.

| Code | Message | Meaning | Recovery Action |
| :--- | :--- | :--- | :--- |
| `4001` | `DeviceDisconnected` | USB/Wi-Fi connection lost. | Reconnect device, run `doctor`. |
| `4002` | `BuildFailed` | Gradle build error. | Check `project://build_logs`. |
| `4003` | `ElementNotFound` | UI Selector matched 0 nodes. | Use `get_ui_tree` to verify ID. |
| `4004` | `AppNotDebuggable` | `run-as` failed (Release build). | Rebuild with `debuggable true`. |
| `4005` | `PrivateSpaceLocked` | App in Private Space is inaccessible. | Unlock device or move app. |
| `5001` | `SDKNotConnected` | Agent SDK WebSocket is down. | Restart app / Check `adb reverse`. |
| `6001` | `RequiresElicitation` | Tool needs user input (e.g. 2FA). | Agent asks user and retries. |

---
**End of Specification**