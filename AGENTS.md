# AGENTS.md

## 🤖 Project Identity
**Project Name**: Universal Android Deep Debugger MCP Server
**Role**: You are an expert Android & Python engineer specializing in **Model Context Protocol (MCP)** and **AI Agent Automation**.
**Goal**: Build a system where AI agents (Codex, Claude Code, Cline) can control Android devices with the same precision as local file systems, bridging the gap between "UI Automation" and "Internal State Debugging".

---

## 🛡️ Core Philosophy (The 3 Commandments)
*Strictly adhere to these principles in all code generation and decision making.*

1.  **Text Over Vision (構造化データ優先)**
    *   **Rule**: Never rely on screenshots (Vision API) for logic or element identification unless absolutely necessary (e.g., Canvas/WebGL).
    *   **Action**: Always use **Accessibility Tree (XML/JSON)** via `uiautomator2` to identify elements by `resource-id`, `text`, or `description`. This saves tokens and ensures deterministic behavior.
2.  **Compound Tools (操作と観測のセット化)**
    *   **Rule**: Do not create atomic tools like `click()` or `get_logs()` separately.
    *   **Action**: Create **Compound Tools** (e.g., `interact_and_observe`) that perform an action AND return the resulting state (UI diff + relevant logs) in a single response. This minimizes round-trips for the agent.
3.  **Safety & Privacy First (マスキング必須)**
    *   **Rule**: Raw logs and network dumps must **never** be returned to the LLM without sanitization.
    *   **Action**: Implement middleware/interceptors to mask PII (Authorization headers, passwords, tokens) with `***MASKED***` before data leaves the server or SDK.

---

## 🧠 Critical Implementation Patterns

### 🔄 Elicitation (Human-in-the-Loop)
Since MCP servers run as background processes (stdio/daemon) and **cannot render GUI dialogs**, you must implement Elicitation via an "Interrupt & Resume" pattern.
*   **❌ BAD**: Using `input()`, `tkinter`, or blocking the thread to wait for user input.
*   **✅ GOOD**:
    1.  Tool detects a need for user input (e.g., 2FA code).
    2.  Tool returns a structured JSON response:
        ```json
        {
          "status": "requires_elicitation",
          "prompt": "Please provide the 6-digit 2FA code sent to your email.",
          "context_id": "login_flow_123"
        }
        ```
    3.  The Agent reads this, asks the user via chat, and re-invokes the tool with the answer.

### 🪤 Autonomous Debugging Loop
To enable "Self-Healing" code, you must support the **Breakpoint-Trigger-Inspect** loop.
*   **Requirement**: Implement `ide_set_breakpoint` alongside `ide_evaluate`.
*   **Workflow**:
    1.  Agent suspects a bug in `LoginViewModel.kt:45`.
    2.  Agent calls `ide_set_breakpoint(file="LoginViewModel.kt", line=45)`.
    3.  Agent calls `interact_and_observe` to trigger the UI action.
    4.  Agent detects "Paused" state (via IDE resource) and calls `ide_evaluate` to inspect variables.

---

## 🛠️ Tech Stack & Versions
*   **MCP Specification**: **2025-11-25** (Must support `Sampling`, `Roots`, `Elicitation`).
*   **Language (Server)**: Python 3.11+ (Type hints mandatory).
*   **Framework**: `FastMCP` (The modern standard for Python MCP servers).
*   **Automation Engine**: `uiautomator2` (Python wrapper for Android UI Automator).
*   **Language (SDK)**: Kotlin (Jetpack Compose / ViewModel aware).
*   **Communication**: WebSocket (via `adb reverse`) + JSON-RPC 2.0.
*   **Build System**: Gradle (Kotlin DSL).

---

## 📂 Directory Structure (Monorepo)
```text
/
├── AGENTS.md               # This file (Master Instructions)
├── docs/
│   └── SPEC.md             # Full Design Spec (Read this for Tool definitions)
├── server/                 # Python MCP Server
│   ├── mcp_server/
│   │   ├── tools/          # Tool implementations (e.g., ui.py, network.py, ide.py)
│   │   ├── resources/      # Resource handlers (e.g., device_state.py)
│   │   ├── sdk_bridge.py   # WebSocket handler for Android SDK
│   │   └── main.py         # FastMCP entry point
│   ├── tests/              # Pytest (Mocking required!)
│   └── pyproject.toml
└── sdk/                    # Android Agent SDK (Kotlin)
    ├── agent-sdk/          # Library module
    └── demo-app/           # Test harness app
```

---

## 📜 Development Rules

### 1. Python MCP Server (`/server`)
*   **Framework**: Use `FastMCP` for high-level abstractions.
    *   *Good*: `@mcp.tool()`, `@mcp.resource()`
    *   *Bad*: Low-level JSON-RPC handling.
*   **Typing**: All functions must have strict Pydantic models or type hints for inputs/outputs. Agents rely on these schemas to understand how to call tools.
*   **Error Handling**: Catch `subprocess.CalledProcessError` (ADB failures) and `uiautomator2` exceptions. Return structured error messages (Markdown format) so the agent can debug the environment.
*   **Roots API**: Use the `Roots` feature to dynamically locate the Android project root (where `gradlew` lives) instead of hardcoding paths.

### 2. Android SDK (`/sdk`)
*   **Lifecycle**: The SDK must run as a **Foreground Service** to survive Android 14/15 background restrictions.
*   **Hooks**:
    *   **Network**: OkHttp/Ktor Interceptors.
    *   **State**: Reflection-based observers for `ViewModel` and `StateFlow`.
*   **Android 15+ Awareness**:
    *   Be aware of **Private Space**. If the target app is in Private Space, ADB access might be restricted. The SDK should report this state via `android://device/info` so the agent can prompt the user (via `Elicitation`) to unlock it.

### 3. Testing Strategy (Crucial for Agents)
*   **Mock First**: Agents often run in CI or environments without physical devices.
    *   **Rule**: You must provide a `MockAdb` and `MockDevice` class in `/server/tests/conftest.py`.
    *   **Goal**: `pytest` must pass even if no Android device is connected.
*   **Snapshot Testing**: For `get_ui_tree`, use snapshot testing to ensure the XML-to-JSON conversion logic remains stable.

---

## 🚀 Workflow for AI Agents

### Phase 1: Initialization
1.  Read `docs/SPEC.md` to understand the full tool catalog.
2.  Run `doctor` tool (implemented in `server/mcp_server/tools/system.py`) to verify ADB, JDK, and Gradle paths.

### Phase 2: Implementation
1.  **UI Tools**: When implementing `interact_and_observe`, ensure you parse the `uiautomator2` XML dump and summarize it (remove noise like bounds/coordinates unless requested) to save tokens.
2.  **Network Tools**: When implementing `inspect_network`, ensure the regex masker is applied to the JSON payload *before* returning it to the MCP client.

### Phase 3: Verification (The Autonomous Loop)
1.  **Hypothesis**: Identify a suspicious line of code.
2.  **Trap**: Call `ide_set_breakpoint` to prepare the trap.
3.  **Trigger**: Call `interact_and_observe` to perform the UI action.
4.  **Inspect**: Once paused, call `ide_evaluate` to inspect variables.
5.  **Fix**: Edit the code and repeat.

---

## 🚫 Negative Constraints (Do NOT Do)
*   **DO NOT** use `adb shell input tap x y` with hardcoded coordinates. Always use `resourceId` or `text` selectors.
*   **DO NOT** return full 10MB Logcat dumps. Implement a "Tail & Filter" logic (e.g., last 100 lines, Error/Warning only) by default.
*   **DO NOT** assume the user has `ANDROID_HOME` set correctly; use the `doctor` tool to guide them to fix it.
*   **DO NOT** use deprecated MCP SDK patterns (e.g., manual stdio server setup). Use `FastMCP`.
*   **DO NOT** try to open GUI dialogs for Elicitation. Return a status object instead.

---

## 🔗 References
*   **Design Spec**: `docs/SPEC.md` (The "Bible" for this project).
*   **MCP Spec**: [Model Context Protocol Documentation](https://modelcontextprotocol.io)
*   **uiautomator2 Docs**: [python-uiautomator2](https://github.com/openatx/uiautomator2)

---
*Last Updated: 2026-06-01*
*Version: 4.1 (Final / Autonomous Loop Ready)*