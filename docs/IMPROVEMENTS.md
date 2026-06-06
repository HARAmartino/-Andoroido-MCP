# -Andoroido-MCP 改善点ログ

実機検証・実アプリ統合の過程で見つかった、`-Andoroido-MCP` 本体（MCPサーバー／Agent SDK）への改善候補を記録する。各項目は「発見の経緯／問題／推奨修正」を含む。

---

## 1. 実機 uiautomator2 が `DeviceClient` プロトコルを満たさない【対応済み】

- **経緯**: MCPツールを実機で順に実行したところ、`get_ui_tree` 以外の全UIツールが失敗。
- **問題**: `_default_ui_context()` が生の `uiautomator2.connect()` を返していたが、ツールが期待する
  セレクター文字列ベースの `DeviceClient`（`click(selector)`/`input_text`/`scroll`/`get_recent_logs`）を満たさない。
  生デバイスは座標ベースで、`input_text`/`scroll`/`get_recent_logs` は存在しない。
- **対応**: `mcp_server/device.py` に `UiAutomator2Adapter` を追加し、`_default_ui_context()` でラップ（コミット `333cdbc`）。
- 詳細は `docs/TROUBLESHOOTING.md` §7。

---

## 2. Agent SDK が `SdkBridgeClient` を共有できない（host-app 統合の阻害）

- **経緯**: 実アプリ `com.haramartino.botbuilder`（BotBuilder）に Agent SDK を統合する際に判明。
- **問題**: `AgentService.onCreate()` が `SdkBridgeClient` を **private フィールド**として生成し、外部に公開しない。
  一方、テレメトリの送信元である `NetworkInterceptor` / `ViewModelObserver` は host-app の DI グラフ
  （OkHttpClient 構築時など）で生成され、サービスより前・独立に作られる。両者が **同じ接続に到達する手段がない**。
  結果として「サービスはWS接続するが、ネットワーク傍受がそのbridgeへ送れない」状態になる。
- **推奨修正**: プロセス共有のホルダー `AgentBridge`(object) を追加し、
  - `AgentService` が生成時に `AgentBridge.client = bridgeClient` を公開、停止時に `null` クリア。
  - `NetworkInterceptor` / `ViewModelObserver` は構築時に bridge を要求せず、送信時に `AgentBridge.send(...)` を呼ぶ
    （未接続時は `false` を返して例外を投げない）。
  これにより「生成順の依存」を完全に排除できる。
- **状態**: BotBuilder 側の統合コピーで実装済み。upstream の `sdk/agent-sdk` にも同様の `AgentBridge` を入れるべき。

---

## 3. `MessageMasker` が API キーヘッダ（`X-Api-Key` 等）をマスクしない【要対応・セキュリティ】

- **経緯**: BotBuilder の `NetworkModule` を見ると、LLM API キーは `Authorization` ではなく
  `X-Api-Key` / `x-api-key` / `X-Goog-Api-Key` / `x-goog-api-key` / `api-key` ヘッダで送られている
  （`HttpLoggingInterceptor.redactHeader(...)` でこれら全てを redact 指定済み）。
- **問題**: `MessageMasker`（SDK側）と `sanitize_log`（サーバ側 `sdk_bridge.py`）は **`Authorization` ヘッダしかマスクしない**。
  そのため `NetworkInterceptor` を API キー注入後に置くと、これらのヘッダ値が **マスクされず** テレメトリに乗り、
  ログ／バグレポートに漏れる恐れがある。
- **暫定回避（統合側で実施）**: BotBuilder では `NetworkInterceptor` を **`ApiKeyInterceptor` より前**に配置し、
  キー注入前のリクエストを記録することで漏えいを回避。
- **推奨修正（upstream）**: マスク対象ヘッダ接頭辞に
  `x-api-key` / `api-key` / `x-goog-api-key` を追加する。具体的には
  - `sdk_bridge.py`: `_MASKED_HEADER_PREFIXES` に上記を追加し、文字列パターンにも
    `"X-Api-Key: ..."` 形式の正規表現を追加。
  - `MessageMasker.kt`: `RULES` に同等の正規表現を追加。
  既存のモックテスト（`Authorization`/`password`/`token`/`credit_card`）は不変のまま、対象を拡張する。

---

## 4. `build_and_deploy` のデフォルトパッケージが固定 (`com.android.mcp.demo`)

- **経緯**: 実機に入っていたのは `com.haramartino.botbuilder` で、E2E スクリプトや想定が
  `com.android.mcp.demo` 固定だった。
- **推奨**: パッケージ名／起動 Activity を引数または Roots 経由のマニフェスト解析から解決できるようにする
  （E2E スクリプト `tests/e2e_test.py` は既に `--package` 引数あり。サーバ側ツールにも同様の柔軟性を）。

---

## 5. `SdkBridgeClient.connect()` が接続済みでも再接続し続ける【要対応・リーク】

- **経緯**: BotBuilder 実機統合後、MCP ブリッジのログに `SDK client connected` が
  **約30秒ごとに繰り返し**出力された（接続は1つのはずなのに何度も「接続」イベント）。
- **問題**: `SdkBridgeClient.connect()` のループが、接続成功・失敗に関わらず
  バックオフ間隔ごとに `openWebSocket()` を呼び続ける設計になっている:
  ```kotlin
  while (active) { openWebSocket(); delay(backoffMs); backoffMs = min(backoffMs*2, MAX) }
  ```
  既に接続済みでも、バックオフが上限（30秒）に達した後は **30秒ごとに新しい WebSocket を開く**。
  古いソケットは明示的に閉じられないため、接続リーク／サーバ側の不要な connect/disconnect ログを生む。
  サーバ側 `_handle_ws_client` も接続のたびに `SDK_CONNECTED` を emit するため、イベントが重複する。
- **推奨修正（upstream `sdk/agent-sdk/.../SdkBridgeClient.kt`）**:
  - `openWebSocket()` を「切断時のみ」呼ぶ。例えば `onOpen` で接続が確立したら、
    `onFailure`/`onClosed` が発火するまで再オープンしない（接続状態を待つ suspend or フラグで制御）。
  - もしくは接続中はバックオフをリセットし、`isConnected` が false の時だけ再オープンする。
- **状態**: BotBuilder の統合コピーにも同じ挙動あり（upstream 由来）。両方で修正が必要。

---

## 6. UIツリーのトークン消費が過大 → `compact` スナップショットを既定化【対応済み】

- **経緯**: 実運用で「`-Andoroido-MCP` 使用時のトークン消費が大きすぎる」と判明。原因を追うと
  浪費はほぼ全て **UIツリーのダンプ**に集中していた。
- **問題**:
  - `get_ui_tree(format="xml"/"json")` は `dump_hierarchy()` の**生XMLを丸ごと**返す（Compose画面で2万〜6万字）。
  - 旧既定の `format="summary"` も「resource-id を持つ全ノード」を出すため、**タップ不能なレイアウト用
    `FrameLayout`/`ViewGroup` が大量混入**し、`com.haramartino.botbuilder:id/...` の長い接頭辞を毎行繰り返す。
  - エージェントは**毎ステップ画面全体を再ダンプ**するため、ループで掛け算的に膨張。
- **着想（PC/ブラウザ操作AIの手法）**: computer-use や `browser_snapshot` は **DOM全体を渡さず**、
  「操作可能／意味のある要素だけ」に絞った**アクセシビリティ・スナップショット**＋短い参照を返す。
- **対応**: `tools/ui.py` に `_xml_to_compact()` と `format="compact"` を追加し、`get_ui_tree` の**既定に変更**。
  - clickable / long-clickable / checkable / scrollable / focusable / EditText か、text/desc を持つノードのみ出力。
  - レイアウト専用コンテナ（テキストも操作性も無い）は除外。
  - resource-id の `package:id/` 接頭辞を剥離。1要素1行 `[role] "text" -> #selector`。
  - `COMPACT_MAX_TEXT=48`（テキスト切り詰め）/ `COMPACT_MAX_NODES=80`（上限超過は `+N more` 表記）。
  - セレクタは id > text > desc の順で、そのまま `interact_and_observe` に渡せる形にして**生ツリー再取得を不要化**。
- **効果（合成計測, レイアウト60+操作要素9の画面）**: 生XML比 **98%減** / 旧summary比 **92%減**
  （~2568 tok → ~68 tok）。既存 `summary`/`xml`/`json` は温存（後方互換）。
- **テスト**: `test_ui.py` に compact 用3件追加（既定=compact / ロール分類・レイアウト除外 / テキスト切り詰め）。
  既存93テスト不変で全70 unit pass。
- **追加対応済み（往復削減）**: `interact_and_observe` の事後観測を **compact diff** 化（`_compact_diff`）。
  操作後に「追加(`＋`)/削除(`−`)された操作可能ノードだけ」を返し、`UI Diff` セクションに埋め込む。
  これにより**操作のたびに別途 `get_ui_tree` を呼ぶ往復が不要**になり、ループ全体のトークンをさらに削減。
  - 同一XML → `No UI change detected`、座標等のみ差分 → `UI changed (no actionable difference)`。
  - 差分行は各 `COMPACT_DIFF_MAX_LINES=20` で上限。`test_ui.py` に3件追加（計73 unit pass）。
- **視覚フォールバック（対応済み）**: `get_screenshot` ツールを追加（`capture_screenshot`/`_downscale_png`）。
  Compose/Canvas/WebView 等で semantics が空になり compact が「No actionable nodes」になる盲点用の
  **明示的なエスケープハッチ**。既定では使わずテキストツリーを優先。`max_width=720` に縮小してトークンを上限化。
  - **プライバシー**: スクショは画面を逐語的に取り込み PII を含み得る／テキストマスク不可。
    **一時的なモデル文脈としてのみ使用**し、レポート・セッション履歴・ログには**永続化しない**旨を docstring に明記。
  - `device.UiAutomator2Adapter.screenshot()` が u2 の PIL スクショを PNG bytes に変換（実機ロジックは IF 背後）。

### ② `e5` ref→selector マップ → 見送り（実装しない）

- **判断**: トークン削減目的では割に合わない。compact は既に接頭辞を剥がし `#send_button` 等の短いセレクタを
  出しているため、`e5` 化の節約は1行あたり1〜2トークンで誤差。一方 ref マップは
  `get_ui_tree`→次 `interact_and_observe` の**間にサーバ側状態**を要し、画面が非同期変化すると
  `e5` が古い要素を指す＝**タイミングレース由来の誤タップ**を新規に生む（本ハードニングが潰している不具合クラス）。
- **代替（ステートレスで本来の便益を実装）**: ref の真価は「一意セレクタを持たない要素の操作」。
  これを状態無しで達成するため、compact で **id/text/desc を持たない操作可能ノードに座標ハンドル `@x,y`**
  （`bounds` 中心）を付与し、`UiAutomator2Adapter.click/long_click` が `@x,y` を座標タップとして処理する
  （`_parse_coord`）。クロスコール状態が無いのでスタレ／レースが発生しない。
- **テスト**: `test_ui.py`（bounds中心・座標フォールバック・スクショPNG・縮小passthrough）＋
  `test_device_adapter.py`（`@x,y` 座標タップが selector 解決を迂回）。全79 unit pass。
