# Box1 SSO

One RH-SSO 7.6 instance, managed by `rhsso-operator` using
`keycloak.org/v1alpha1`, with a separately managed PostgreSQL 13 database.
The `k8s.keycloak.org/v2beta1` API does not apply to this operator.

Public URL: https://keycloak.apps.ocp.box1.org/auth/
Realm issuer: https://keycloak.apps.ocp.box1.org/auth/realms/box1

PostgreSQL uses the OpenShift catalog's PostgreSQL 13 image, pinned by digest,
and a 10 GiB `postgres-data` PVC on `lvms-vg1`. The Deployment uses Recreate
to avoid simultaneous database processes using the volume. The PVC is protected
from Argo CD pruning and Application deletion. This is a single-instance
installation; the PVC is not a backup and node-local LVM storage provides no HA.

## Credentials

`keycloak-db-secret` is provisioned directly in the namespace before sync and
is intentionally excluded from Git. Preserve it when restoring the database.
Required string keys:

- `POSTGRES_DATABASE`: `keycloak`
- `POSTGRES_USERNAME`: `keycloak`
- `POSTGRES_PASSWORD`: generated random password
- `POSTGRES_EXTERNAL_ADDRESS`: `postgres-db.keycloak.svc.cluster.local`
- `POSTGRES_EXTERNAL_PORT`: `5432`
- `POSTGRES_HOST`: `keycloak-postgresql` (operator-managed alias Service)
- `POSTGRES_VERSION`: `13`
- `SSLMODE`: `disable` (database traffic remains inside the cluster)

The RH-SSO operator creates the initial administrator credentials in
`credential-box1-keycloak`. Retrieve them from the cluster only when needed.
Do not commit either credential Secret.

## TLS and reconciliation

cert-manager issues `keycloak-tls` through `letsencrypt-production` using DNS-01.
The Ingress consumes that Secret. OpenShift generates a reencrypt Route to the
operator-managed `keycloak:8443` Service, whose backend certificate is issued by
the OpenShift service CA. Operator external access is disabled so it does not
create a competing Route. The external frontend URL includes RH-SSO's `/auth`
context path.

Argo CD deploys the database and Certificate in wave -1, Keycloak and ingress
in wave 0, and the `box1` realm in wave 1. Automatic pruning is disabled.
The installed operator CSV was Succeeded on OpenShift 5.0.0-rc.7 during
preflight; this is an operational observation, not a vendor support claim.
OpenShell is outside this application's scope.

## OpenShell client

`realm/openshell-client.yaml` configures the public `openshell-cli` client for the
v0.1.5 CLI's Authorization Code flow with S256 PKCE and native loopback callback.
The audience mapper adds `openshell-cli` to access tokens. Password grants,
implicit flow, and service accounts are disabled. The realm declares
`openshell-admin` and `openshell-user`; on the existing realm those roles were
also bootstrapped through the Admin API because the legacy operator did not
add them during realm update.

The `mike` account was provisioned through the Admin API with both roles.
Its temporary initial password is in the out-of-Git Kubernetes Secret
`openshell-mike-initial-login` in namespace `keycloak`. First browser login
requires changing that password. User credentials and password changes remain
in the persistent Keycloak database; no password is declared in these manifests.


## Repository layout and ownership

- `operator/`: namespace, OperatorGroup and Subscription; owned by the existing
  `rhsso-operator` Application.
- `database/`: PostgreSQL Deployment, Service and protected PVC.
- `instance/`: Keycloak resource, public Certificate and Ingress.
- `realm/`: box1 realm and OpenShell CLI client.

The root Kustomization aggregates `database/`, `instance/` and `realm/` for the
existing `keycloak` Application. It excludes `operator/` to avoid dual ownership.
The directory split preserves all resource names, specs, sync waves and the
existing Application identity. Each non-operator resource has one owner.

Render the two independent targets with:

```bash
kubectl kustomize platform/identity/keycloak/operator
kubectl kustomize platform/identity/keycloak
```

`applications/keycloak.yaml` now points to the aggregate root. On a cluster
without `box1-root`, update that existing child Application explicitly after
publishing the new path. Do not bootstrap a new root solely for this path change.
