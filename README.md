# box1-gitops

Platform configuration for box1. `applications/` contains the child Applications
registered by the `box1-root` app-of-apps when that root is installed.

- [Developer Hub](platform/developer-hub/README.md): separate manual-sync
  Operator and instance Applications.
- [RH-SSO / Keycloak](platform/identity/keycloak/README.md): separate Operator
  Application and a single Application aggregating database, instance, and realm.
- [Development workloads](https://github.com/box1-org/box1-workloads-dev): service
  Applications and workload manifests, discovered by `applications/workloads-dev.yaml`.
  Service repositories retain their original `deploy/` manifests.
- [Pipelines](platform/pipelines/README.md): Operator installation, shared Tasks,
  scoped GitHub App credentials, and [automated CI/CD](platform/pipelines/AUTOMATION.md).
- [OpenShift AI](platform/openshift-ai/README.md): lab-only AI 3.4.2 installation,
  CPU workbench, NooBaa connection and KServe inference validation.
- [Trusted Profile Analyzer](platform/trusted-profile-analyzer/README.md): RHTPA 3.1.1,
  dedicated PostgreSQL/NooBaa, Keycloak login and scoped SBOM ingestion.
- [OpenShell](platform/openshell/README.md): validated Helm values and a staged
  Argo Application. The existing Helm release remains live owner; the staged
  Application is deliberately outside `applications/` and is not installed.

Credentials remain in Kubernetes Secrets, referenced by name. Do not commit live
Secret exports, Helm backup manifests, tokens, private keys, or initial passwords.
