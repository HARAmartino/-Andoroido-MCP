#!/bin/bash

# 1. 出力先ディレクトリが存在しない場合は作成
mkdir -p .github

# 2. AGENTS.mdが存在するかチェック
if [ ! -f "AGENTS.md" ]; then
    echo "Error: AGENTS.md not found."
    exit 1
fi

# 3. ヘッダー（自動生成である旨の注意書き）を付与してコピー
# ※LLMに対して「これはAGENTS.mdから同期されたファイルだ」と認識させるためのメタデータを含めます
{
    echo "<!-- AUTO-GENERATED FILE: DO NOT EDIT DIRECTLY -->"
    echo "<!-- This file is synchronized from AGENTS.md via Git hooks. -->"
    echo "<!-- To update, edit AGENTS.md and commit. -->"
    echo ""
    cat AGENTS.md
} > .github/copilot-instructions.md

# 4. 同期完了メッセージ（Gitコミット時に表示される）
echo "✅ Synchronized AGENTS.md -> .github/copilot-instructions.md"