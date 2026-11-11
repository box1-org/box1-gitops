#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT

helm template box1-rhdp "$root/rhdp" \
  --set gitops.repoURL=https://github.com/box1-org/box1-gitops.git \
  --set gitops.revision=rhdp \
  --set deployer.domain=apps.cluster.example.com >"$rendered"

test "$(rg -c '^kind: Application$' "$rendered")" -eq 1
rg -q '^  name: keycloak-rhbk$' "$rendered"
! rg -q 'rhsso-operator|keycloak.org/v1alpha1' "$rendered"

helm template box1-rhbk "$root/rhdp/components/keycloak-rhbk" \
  --set deployer.domain=apps.cluster.example.com \
  --set keycloak.instanceName=keycloak >"$rendered"

rg -q 'developer-hub.apps.cluster.example.com' "$rendered"
rg -q 'keycloakCRName: "keycloak"' "$rendered"
! rg -q 'apps.ocp.box1.org' "$rendered"
