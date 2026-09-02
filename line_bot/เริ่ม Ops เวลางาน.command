#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
bash scripts/run_line_bot_tunnel.sh
read -r -p "กด Enter เพื่อปิดหน้าต่าง..."
