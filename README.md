# box1-gitops

Platform configuration for box1. `applications/` contains the child Applications
registered by the `box1-root` app-of-apps when that root is installed.

- [Developer Hub](platform/developer-hub/README.md): separate manual-sync
  Operator and instance Applications.
- [RH-SSO / Keycloak](platform/identity/keycloak/README.md): separate Operator
  Application and a single Application aggregating database, instance, and realm.
- [OpenShell](platform/openshell/README.md): validated Helm values and a staged
  Argo Application. The existing Helm release remains live owner; the staged
  Application is deliberately outside `applications/` and is not installed.

Credentials remain in Kubernetes Secrets, referenced by name. Do not commit live
Secret exports, Helm backup manifests, tokens, private keys, or initial passwords.
