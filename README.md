# 📱 Universal Android Deep Debugger MCP Server

**Turn your Android device into a fully-introspectable subsystem for AI Agents.**

[![MCP Specification](https://img.shields.io/badge/MCP-2025--11--25-blue.svg)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

## 🚀 Overview

The **Universal Android Deep Debugger** is an advanced Model Context Protocol (MCP) server that bridges the gap between **AI Coding Agents** (Codex, Claude Code, Cline, Cursor) and **Android Devices**.

Unlike traditional automation tools that only scratch the surface (UI clicks/swipes), this server grants AI agents **deep introspection capabilities**—allowing them to read ViewModels, intercept Network traffic, query internal Databases, and control the IDE debugger, effectively treating the Android device as a local subsystem of the development PC.

### ✨ Key Features

*   **🔄 Agentic Loop Optimization**:
    *   **`interact_and_observe`**: A compound tool that performs a UI action and instantly returns the **UI Diff (XML)** and **Logcat** in a single turn, minimizing token usage and latency.
*   **🔍 Deep Inspection (Beyond UI)**:
    *   **`dump_viewmodel`**: Inspect the internal state (`StateFlow`/`LiveData`) of your app.
    *   **`inspect_network`**: View intercepted HTTP requests/responses (with auto-masking).
    *   **`query_internal_db`**: Execute SQL directly against the app's SQLite/Room database.
*   **🏗️ Build & Deploy Pipeline**:
    *   **`build_and_deploy`**: Triggers Gradle builds and installs the APK to the connected device/emulator automatically.
*   **🧠 IDE Integration (Autonomous Debugging)**:
    *   **`ide_set_breakpoint`** & **`ide_evaluate`**: Agents can set traps in Android Studio, trigger bugs via UI, and inspect variables at runtime without human intervention.
*   **🛡️ Safety & Privacy**:
    *   **Auto-Masking**: Automatically redacts PII (Passwords, Tokens) from logs and network dumps.
    *   **Elicitation**: Securely asks the user for sensitive input (e.g., 2FA codes) via the chat interface when needed.
*   **🤖 Android 15+ Ready**:
    *   Full support for **Private Space** detection and handling.

---

## 🏗️ Architecture

```mermaid
graph TD
    Agent[AI Agent (Codex/Claude/Cline)] <-->|JSON-RPC (MCP)| Server[MCP Server (Python)]
    
    subgraph "Host PC"
        Server <-->|Roots API| FS[Project Source]
        Server <-->|Gradle| Build[Build System]
        Server <-->|WebSocket| Gateway[SDK Gateway]
        Server <-->|JDWP| IDE[Android Studio]
    end
    
    subgraph "Android Device"
        OS[Android OS 15+] <-->|ADB| Server
        App[Target App] <-->|Hook| SDK[Agent SDK]
        SDK <-->|WebSocket| Gateway
    end
```

---

## 🛠️ Installation & Setup

### 1. Prerequisites
*   **Python 3.11+**
*   **ADB** (Android Debug Bridge) installed and in `PATH`.
*   **Android Device** (Physical or Emulator) with **USB Debugging** enabled.
*   *(Optional)* **Android Studio** running for IDE integration features.

### 2. Install the Server
You can run the server directly using `uvx` (recommended) or install it via pip.

```bash
# Using uv (Fast Python package installer)
uvx android-deep-debugger-mcp

# OR clone and install for development
git clone https://github.com/your-repo/android-deep-debugger-mcp.git
cd android-deep-debugger-mcp
pip install -e .
```

### 3. Configure MCP Client
Add the server configuration to your AI client (Claude Desktop, Cursor, Cline, etc.).

**Example (`claude_desktop_config.json` or `.cursor/mcp.json`):**

```json
{
  "mcpServers": {
    "android-deep-debugger": {
      "command": "uvx",
      "args": ["android-deep-debugger-mcp"],
      "env": {
        "ANDROID_HOME": "/path/to/your/android/sdk"
      }
    }
  }
}
```

---

## 📦 Android Agent SDK (Optional but Recommended)
To unlock **Deep Inspection** features (Network, ViewModel, DB), you must embed the **Agent SDK** into your Android app.

1.  **Add Dependency**:
    ```kotlin
    dependencies {
        debugImplementation("com.example:agent-sdk:1.0.0")
    }
    ```
2.  **Initialize**:
    ```kotlin
    // In your Application class or Main Activity
    if (BuildConfig.DEBUG) {
        AgentSDK.init(this)
    }
    ```
3.  **Connect**: The SDK automatically connects to the MCP Server via `adb reverse` when the app starts.

---

## 📖 Usage Examples

### Scenario 1: The "Self-Healing" Login Bug
**User**: "The login button isn't working. Fix it."
**Agent Workflow**:
1.  **`build_and_deploy`**: Installs the latest code.
2.  **`interact_and_observe(action="click", target="btn_login")`**: Clicks the button.
3.  **Observation**: Agent sees `NetworkTrace` shows `401 Unauthorized` but UI shows nothing.
4.  **`dump_viewmodel(class_name="LoginViewModel")`**: Agent sees `errorState` is populated but not rendered.
5.  **Fix**: Agent edits `LoginScreen.kt` to observe `errorState`.
6.  **Verify**: Repeats loop until green.

### Scenario 2: Autonomous Debugging
**User**: "Find out why the app crashes on the Settings screen."
**Agent Workflow**:
1.  **`ide_set_breakpoint(file="SettingsViewModel.kt", line=42)`**: Sets a trap.
2.  **`interact_and_observe(action="click", target="nav_settings")`**: Triggers the crash/pause.
3.  **`ide_evaluate(expression="userPreferences.repository")`**: Inspects variables while paused.
4.  **`generate_bug_report`**: Creates a Markdown report with stack traces and variable dumps.

---

## 📂 Project Structure

*   **`AGENTS.md`**: Master instructions for AI Agents (Codex/Claude) working on this repo.
*   **`SPEC.md`**: Detailed technical specification of Tools and Resources.
*   **`server/`**: Python source code for the MCP Server.
*   **`sdk/`**: Kotlin source code for the Android Agent SDK.

---

## 🤝 Contributing (AI-First Development)

This project is designed to be maintained by AI Agents.
If you are an AI Agent reading this: **Please read `AGENTS.md` first.** It contains strict rules regarding architecture, testing (Mock First), and MCP protocol versions.

**Human Developers**:
We use a Git Hook system to sync `AGENTS.md` to `.github/copilot-instructions.md`.
Run `bash setup-hooks.sh` after cloning to enable automatic synchronization.

---

## 📜 License
MIT License.