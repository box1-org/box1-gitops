# GitLab CE

Self-provisioned GitLab CE for Box1, managed by the Argo CD app `gitlab`. Manual sync: each sync re-runs the idempotent bootstrap. The evidence and the comparison with Forgejo are in box1-docs `architecture/gitlab-proof-transaction.md` ([box1-docs#164](https://github.com/box1-org/box1-docs/issues/164)).

## Components

- **GitLab:** one Omnibus pod (`gitlab/gitlab-ce`, pinned by digest; see `deployment.yaml`).
  - Memory: limit 4 GiB, request 3 GiB. Steady state is about 2.6–2.9 GiB.
  - Settings: `gitlab.rb` (Puma single mode, Sidekiq concurrency 5; registry, KAS, Pages, Mattermost and Prometheus off).
  - Needs the `anyuid` SCC, because Omnibus starts as root.
  - Storage: PVC `gitlab-data` (20 Gi).
  - Route: `gitlab.apps.ocp.box1.org` (edge TLS).
- **Root token:** `seed-token.sh` runs in the container. It makes sure root has a token equal to `gitlab/gitlab-admin`, using one `gitlab-rails runner` call only when needed.
- **Bootstrap:** `bootstrap/bootstrap.py`, run by the Sync and PostSync hook Jobs. It configures:
  - **Instance settings:** sign-up off, private by default.
  - **`box1-gl`:** service projects, created by RHDH.
  - **`box1-gl-gitops`:** the `workloads-proof` GitOps project. `promote-bot` is its only Maintainer, and "Pipelines must succeed" plus a protected `main` gate merges.
  - **`box1-org`:** public mirror of github.com/box1-org.
  - **Bot accounts:** each has a scoped token.
  - **Consumer Secrets:** see the table below.
- **CI lane (`ci/`, namespace `box1-gl-ci`):** PaC Repository CRs and a registrar CronJob, which adds the Repository CR and project webhook for new `box1-gl` projects. Also the `gitlab-gitops-validate` and `gitlab-gitops-promote` Tasks, and the Argo CD Application `gitlab-proof-workloads` (deploys to `box1-gl-dev`).
- **Mirror (`mirror/`):** CronJob `github-mirror`, every 15 minutes. It mirrors every non-archived github.com/box1-org repository (branches and tags, exactly) into public projects in `box1-org`. GitHub stays the source of truth: GitLab copies are overwritten. Don't start a manual run while a scheduled one is active.

## Secrets (all generated; nothing in Git)

| Secret | Written by | Used by |
|---|---|---|
| `gitlab/gitlab-admin` | admin-secret Job | GitLab container (root password and token), bootstrap |
| `rhdh/developer-hub-gitlab-secrets` (`GITLAB_TOKEN`) | bootstrap | RHDH `integrations.gitlab` |
| `box1-gl-ci/gitlab-pac`, `box1-gl-ci/gitlab-promote` | bootstrap | PaC, registrar, promote Task |
| `openshift-gitops/gitlab-repo-creds` | bootstrap | Argo CD (read-only) |
| `gitlab/gitlab-dev-token`, `gitlab/gitlab-mirror-token` | bootstrap | developer account, mirror CronJob |

**Hand-made, per user:** a Dev Spaces GitLab personal access token Secret in the user's Dev Spaces namespace (`che.eclipse.org/scm-personal-access-token-name: gitlab`, `scm-url: https://gitlab.apps.ocp.box1.org`).

## Recovery

- **Remove:** delete the Argo CD apps `gitlab-proof-workloads` and `gitlab`; prune removes the `gitlab`, `box1-gl-ci` and `box1-gl-dev` namespaces, PVC included. Then delete the consumer Secrets in `rhdh` and `openshift-gitops`.
- **Backup and restore:** not set up.
