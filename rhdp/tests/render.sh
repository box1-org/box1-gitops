#!/usr/bin/env bash
# Render checks for the RHDP entry chart. Needs helm, kubectl and a Python
# with PyYAML (set PYTHON to choose the interpreter).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
python=${PYTHON:-python3}

helm lint "$root/rhdp" \
  --set deployer.domain=apps.cluster-test.example.com \
  --set gitops.repoURL=https://github.com/box1-rhdp/box1-gitops.git >/dev/null

for chart in "$root"/rhdp/components/*/; do
  helm lint "$chart" --set deployer.domain=apps.cluster-test.example.com >/dev/null
done

"$python" "$root/rhdp/tests/check.py" "$@"
