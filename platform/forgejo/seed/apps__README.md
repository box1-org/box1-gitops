# apps/

One directory per proof service: `deployment.yaml`, `service.yaml`, `route.yaml`.
Changes arrive only through promotion PRs opened by `promote-bot`
(`forgejo-gitops-promote`), checked by `workloads-proof-validate` and merged
pinned to the PR head. Argo CD Application `forgejo-proof-workloads` deploys
this directory to `box1-fj-dev`.
