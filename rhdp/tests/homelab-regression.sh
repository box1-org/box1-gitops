#!/usr/bin/env bash
# Homelab regression check for platform/ changes made for RHDP.
#
# For every in-repo path that applications/*.yaml deploys on the homelab,
# compare `kubectl kustomize` output between the merge base with origin/main
# and the working tree. The output must be identical, except for paths with
# a reviewed golden diff in rhdp/tests/homelab-diffs/<name>.diff (hunks only;
# the two header lines are ignored).
#
#   rhdp/tests/homelab-regression.sh            # check
#   rhdp/tests/homelab-regression.sh --update   # rewrite the golden diffs
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
goldens="$root/rhdp/tests/homelab-diffs"
update=false
[ "${1:-}" = --update ] && update=true

base=$(git -C "$root" merge-base origin/main HEAD)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git -C "$root" archive "$base" platform | tar -x -C "$tmp"

paths=$(grep -h '^ *path: platform/' "$root"/applications/*.yaml | awk '{print $2}' | sort -u)
golden_for() {
  case "$1" in
    platform/pipelines/ci) echo pipelines-ci ;;
    platform/developer-hub) echo developer-hub ;;
    *) echo "" ;;
  esac
}

fail=0
for p in $paths; do
  [ -d "$root/$p" ] || continue
  kubectl kustomize "$tmp/$p" >"$tmp/before.yaml"
  kubectl kustomize "$root/$p" >"$tmp/after.yaml"
  diff -u --label "main:$p" --label "branch:$p" "$tmp/before.yaml" "$tmp/after.yaml" >"$tmp/diff" || true
  name=$(golden_for "$p")
  if [ -z "$name" ]; then
    if [ -s "$tmp/diff" ]; then
      echo "[FAIL] $p changed for the homelab:"; head -20 "$tmp/diff"; fail=1
    else
      echo "[ok]   $p unchanged"
    fi
    continue
  fi
  if $update; then
    cp "$tmp/diff" "$goldens/$name.diff"; echo "[upd]  $p -> homelab-diffs/$name.diff"; continue
  fi
  if diff -q <(tail -n +3 "$tmp/diff") <(tail -n +3 "$goldens/$name.diff") >/dev/null; then
    echo "[ok]   $p matches reviewed diff homelab-diffs/$name.diff"
  else
    echo "[FAIL] $p differs from the reviewed diff homelab-diffs/$name.diff:"
    diff <(tail -n +3 "$goldens/$name.diff") <(tail -n +3 "$tmp/diff") | head -20
    fail=1
  fi
done
exit $fail
