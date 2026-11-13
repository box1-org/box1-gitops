# apps/

One directory per proof service: `deployment.yaml`, `service.yaml`, `route.yaml`.
Changes arrive only through promotion merge requests opened by `promote-bot`
(`gitlab-gitops-promote`), checked by `workloads-proof-validate` and merged
pinned to the PR head. Argo CD Application `gitlab-proof-workloads` deploys
this directory to `box1-gl-dev`.
