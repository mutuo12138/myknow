#!/usr/bin/env bash
set -euo pipefail

echo "OS: $(uname -s)"
echo "Architecture: $(uname -m)"
sw_vers 2>/dev/null || true
python3 --version 2>/dev/null || echo "Python 3: missing"
node --version 2>/dev/null || echo "Node.js: missing"
npm --version 2>/dev/null || echo "npm: missing"
xcode-select -p 2>/dev/null || echo "Xcode Command Line Tools: missing"
