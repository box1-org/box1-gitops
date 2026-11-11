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

helm template box1-operate "$root/rhdp/components/operate" \
  --set deployer.domain=apps.cluster.example.com \
  --set storage.rwoClass=example-rwo \
  --set storage.objectBucketClass=example-obc >"$rendered"

test "$(rg -c '^apiVersion:' "$rendered")" -eq 67
! rg -q 'apps.ocp.box1.org|lvms-vg1|installPlanApproval: Manual' "$rendered"

helm template box1-operate-operators "$root/rhdp/components/operate-operators" >"$rendered"

test "$(rg -c '^apiVersion:' "$rendered")" -eq 21
rg -q 'installPlanApproval: Automatic' "$rendered"
! rg -q 'installPlanApproval: Manual' "$rendered"

helm template box1-rhdp-operate "$root/rhdp" \
  --set gitops.repoURL=https://github.com/box1-org/box1-gitops.git \
  --set gitops.revision=rhdp \
  --set deployer.domain=apps.cluster.example.com \
  --set profiles.operate=true \
  --set components.operate.enabled=true \
  --set components.operateOperators.enabled=true \
  --set components.operateNetwork.enabled=true >"$rendered"

test "$(rg -c '^kind: Application$' "$rendered")" -eq 4
rg -q '^  name: box1-operate-operators$' "$rendered"
rg -q '^  name: box1-operate-network$' "$rendered"
