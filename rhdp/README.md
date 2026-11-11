# Box1 RHDP installation

This is the Helm entry point for the RHDP
`ocp4_workload_field_content` role. That role injects `deployer.domain`,
`deployer.apiUrl`, `gitops.repoURL`, and `gitops.revision`; this chart creates
only the profile-enabled Argo CD child Applications.

The default is deliberately minimal: `core` plus `rhbk`, which renders only
the parameterized RHBK Keycloak bootstrap target. It does not render the
legacy RH-SSO operator or any `keycloak.org/v1alpha1` resources.

Enable a profile and its relevant component flags together. Components are
off by default where their operator, credentials, or capacity are not part of
the base RHDP cluster. For example, enabling `developer` alone does not install
Developer Hub until `components.developerHubOperator.enabled` and
`components.developerHub.enabled` are also set to `true`.

## Required preflight

- OpenShift GitOps and a running RHBK `Keycloak` instance must already exist;
  the chart never manages either operator subscription or a second Keycloak
  server.
- The default `keycloak.instanceName: keycloak` assumes the platform-provided
  instance uses the existing `keycloak-pgsql-user` database Secret and
  `keycloak-initial-admin` bootstrap-admin Secret in the `keycloak` namespace.
  The chart creates only the one-time `box1` realm import against that instance.
- Select a storage class and object-bucket class before enabling stateful
  profiles. `storage.rwoClass` is consumed by the RHBK chart; the remaining
  platform manifests still need their hostname/storage overlay migration
  before their components are enabled.

## Rendering locally

```bash
helm template box1-rhdp ./rhdp \
  --set gitops.repoURL=https://github.com/box1-org/box1-gitops.git \
  --set gitops.revision=rhdp
./rhdp/tests/render.sh
```

The next RHDP increments should add component-specific Helm/Kustomize overlays
that consume `deployer.domain`, storage, and endpoint values. Do not enable a
component whose existing manifests still contain homelab-only hosts or storage
classes.
