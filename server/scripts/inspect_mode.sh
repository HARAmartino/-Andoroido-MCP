#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec mcp dev mcp_server/main.py
