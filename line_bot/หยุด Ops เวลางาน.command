#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
bash scripts/stop_line_bot.sh
read -r -p "กด Enter เพื่อปิดหน้าต่าง..."
