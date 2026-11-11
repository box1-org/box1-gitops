# Box1 RHBK bootstrap target

This directory is the RHBK 26 alternative to the homelab's legacy
`platform/identity/keycloak` RH-SSO target. It is not referenced by the
default `applications/` directory, so it cannot install a second Keycloak
instance into the homelab by accident.

The target assumes the cluster already has `rhbk-operator` installed in the
`keycloak` namespace. It uses the RHBK v2beta1 `Keycloak` API and requires two
out-of-Git secrets before its first sync:

- `keycloak-db-secret`, with `POSTGRES_USERNAME` and `POSTGRES_PASSWORD`;
- `keycloak-bootstrap-admin`, with `username` and `password`.

`KeycloakRealmImport` is bootstrap-only: it creates a realm when absent but
does not reconcile subsequent configuration updates or delete a realm. It
therefore contains the full first-install catalog: 15 clients, six client
scope mappings, and the four service-account role grants required by the
Developer Hub, scenario controller, and edge sites. Do not apply the legacy
`KeycloakClient` manifests to an RHBK cluster; that API is not installed there.

For the RHDP chart, render this target only when `profiles.rhbk.enabled` is
true, and supply the cluster-specific hostname, database service, and TLS
secret through Helm values. The literal hostname currently mirrors the
homelab and is a placeholder until that chart provides the values.
