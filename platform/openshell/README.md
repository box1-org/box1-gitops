# OpenShell

The existing Helm release `openshell` in namespace `openshell` is the live
owner. Baseline: deployed revision 4, chart/app version 0.1.5.

`values.yaml` is the complete non-secret user-values snapshot of that validated
release, including OpenShift security overrides and the existing sandbox pull
Secret. It can be used as a single values file for a separately authorized
Helm operation; it is not just the TLS overlay. No Helm operation is triggered
by changes here.

- Public gateway: https://openshell.apps.ocp.box1.org
- OIDC issuer: https://keycloak.apps.ocp.box1.org/auth/realms/box1
- Audience: `openshell-cli`; roles: `openshell-admin`, `openshell-user`.
- TLS enabled; anonymous user access disabled.
- Public certificate: `letsencrypt-production` ClusterIssuer, exact public SAN.
- Route: TLS passthrough; internal and public certificates remain separate.

## Staged Application

`application.yaml` describes the proposed future Argo Application using the
OCI chart `ghcr.io/nvidia/openshell/helm-chart` at 0.1.5 and this repository as
its values source. The Application/release name and namespace stay `openshell`.
It has no automated sync policy or deletion finalizer. The values-only Git
source has no `path`, so it cannot recursively deploy other platform resources.

This Application is deliberately outside the root's watched `applications/`
directory. It is not applied to the cluster, referenced by a Kustomization,
or registered by an ApplicationSet. Keep it staged until the explicit
[ownership migration](MIGRATION.md) has been reviewed and authorized.
Merely disabling automated sync would not protect against a manual sync.

## Secret references

Secrets and private keys remain outside Git:

- `openshell-sandbox-dockercfg-sp68l`: current sandbox registry pull credential.
- `openshell-credential-storage-key-encryption-key`: encrypts stored credentials.
- `openshell-jwt-keys`: existing gateway signing identity.
- `openshell-ca-tls`, `openshell-server-tls`, `openshell-client-tls` and
  `openshell-server-external-tls`: cert-manager-managed PKI.
- Keycloak credentials live in the `keycloak` namespace; this chart only needs
  the public issuer URL, client ID, audience and role names.

Do not commit live Secret YAML, private keys, passwords, bearer tokens or raw
Helm manifest backups. Existing live Secrets must be preserved, not regenerated
from an offline Helm render.

## Login

```bash
openshell gateway add https://openshell.apps.ocp.box1.org \
  --name box1-secure \
  --oidc-issuer https://keycloak.apps.ocp.box1.org/auth/realms/box1 \
  --oidc-client-id openshell-cli \
  --oidc-audience openshell-cli
```

The `/auth` prefix is required for the selected RH-SSO distribution.

References: [Argo CD values from a Git source](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/#helm-value-files-from-external-git-repository)
and [NVIDIA OpenShift deployment](https://docs.nvidia.com/openshell/kubernetes/openshift).
