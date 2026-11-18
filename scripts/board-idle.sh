#!/usr/bin/env bash
# Exit 0 only when the board is idle with nobody queued: deploys and real-session tests must not cut off a visitor.
set -euo pipefail
state=$(curl -fsS https://fpga.njason.dev/api/public/board | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status'), d.get('queue_length'), d.get('active_demo'))")
echo "board: $state"
[ "$state" = "idle 0 None" ]
