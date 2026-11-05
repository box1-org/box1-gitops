# OpenShift Dev Spaces

This directory installs the Red Hat OpenShift Dev Spaces Operator and its
`CheCluster` instance through separate Argo CD Applications.

The operator Application is manual-sync because its OLM InstallPlan also uses
manual approval. After the operator and its Dev Workspace Operator dependency
are installed and healthy, sync `dev-spaces` to create the `CheCluster`.

The `CheCluster` intentionally starts with the operator defaults. Add
site-specific workspace, identity, storage, or registry settings here as the
cluster requirements are established.
