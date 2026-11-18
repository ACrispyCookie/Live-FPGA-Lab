#!/usr/bin/env bash
# Run the frontend unit tests on vm2 (no Node locally): sync the tree, then node --test in a throwaway container.
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/deploy-vm2.sh --no-build >/dev/null
ssh vm2 'cd ~/Live-FPGA-Lab/src/frontend && docker run --rm -v "$PWD":/w -w /w node:24-bookworm-slim node --test --experimental-strip-types "src/**/*.test.ts"'
