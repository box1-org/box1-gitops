# OpenShift Dev Spaces

This directory installs the Red Hat OpenShift Dev Spaces Operator and its
`CheCluster` instance through separate Argo CD Applications.

The operator Application is manual-sync because its OLM InstallPlan also uses
manual approval. After the operator and its Dev Workspace Operator dependency
are installed and healthy, sync `dev-spaces` to create the `CheCluster`.

The `CheCluster` mostly keeps the operator defaults. Box1 changes:

- `openVSXURL: https://open-vsx.org`, because the embedded registry lacks the
  Kaoto and Tekton extensions recommended by Box1 devfiles (box1-docs#114).
- At most 3 running workspaces per user.

`sandboxes/` holds one namespace per developer (`<user>-sandbox`) for Quarkus
remote dev of uncommitted code from a workspace (`box1-remote-dev`, from the
Box1 UDI in box1-org/box1-devspaces). Argo CD owns each namespace and its access, not the remote-dev resources inside it. To add a developer, copy
`sandboxes/mike.yaml`. The sandboxes sync with the `dev-spaces` Application.
