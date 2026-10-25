# Phase 1 rollout evidence — 2026-10-24 America/New_York

## Verified live

- Foundation published to `box1-org/box1-gitops` in commit `2039209`.
- Bootstrapped existing `box1-root/application.yaml`; root is Synced/Healthy and
  reconciled the existing child Applications plus the new Pipelines children.
- Argo CD installed the Pipelines Subscription. Reviewed and approved only
  `openshift-operators/install-vtkdj`, containing CSV
  `openshift-pipelines-operator-rh.v1.24.1`. CSV reached Succeeded.
- `TektonConfig/config` Ready=True; Pipelines as Code enabled by Operator defaults.
- `pipelines-operator` and `pipelines-ci` both Synced/Healthy.
- CI Kustomize target passed server-side dry run after the namespace existed.
- Installed PAC Repository `box1-ci/box1-gitops`, matching
  `https://github.com/box1-org/box1-gitops`, with default-branch provenance.
- Webhook Route: https://pipelines-as-code-controller-openshift-pipelines.apps.ocp.box1.org
- Manual PipelineRun `box1-ci/box1-phase1-manual-rsgmv` Succeeded=True,
  one completed task, zero failed/cancelled tasks. It exercised the final smoke
  definition with a digest-pinned UBI image, writable HOME, and `ci-test` identity.
  Run parameter used foundation revision `20392097d4b9652672bc058f89328e966801ade8`;
  this was a direct cluster submission, not execution of that revision by PAC.
- Earlier manual run `box1-phase1-manual-dlb2h` also succeeded but emitted a
  credential-copy HOME warning; the final run fixed it.
- Inspected the first smoke Pod: no projected API-token volume. `ci-test` has
  `automountServiceAccountToken: false`; the final definition uses the same SA.

Verified impersonated authorization checks:

| Account | Permission | Namespace | Result |
| --- | --- | --- | --- |
| ci-build | update imagestreams.image.openshift.io/layers | box1-ci | yes |
| ci-build | create imagestreams.image.openshift.io | box1-ci | yes |
| ci-build | update imagestreams.image.openshift.io/layers | rhdh | no |
| ci-test | update imagestreams.image.openshift.io/layers | box1-ci | no |
| ci-build | create deployments | box1-ci | no |
| ci-test | create deployments | box1-ci | no |
| ci-test | get secrets | box1-ci | no |

For kubectl authorization checks on layers, use the explicit API group and
`--subresource=layers`, for example:

```sh
kubectl auth can-i update imagestreams.image.openshift.io --subresource=layers \
  -n box1-ci --as=system:serviceaccount:box1-ci:ci-build
```

## Pending — exit criterion not met

- User selected a dedicated Pipelines GitHub App. It has not been registered or
  installed by this rollout; Chrome automation was denied.
- `openshift-pipelines/pipelines-as-code-secret` absent at final inspection.
- `box1-ci/gitops-writer` absent at final inspection. A secret/renewal contract
  is documented; it is not configured with a live credential.
- No signed GitHub webhook delivery, GitHub-triggered run, successful PR check,
  or repeated event-to-check test has been observed.
- Registry RBAC was verified. Actual authenticated image push and digest output
  await the Quarkus build task; RBAC checks alone do not prove a working push.

Follow [README.md](README.md) to provision integration Secrets and perform the
GitHub acceptance test. Neither manual run satisfies the Phase 1 exit criterion.
Application scaffolding, Quarkus build/test, GitOps image PR automation, runtime
pull access, and Argo-managed application deployment belong to subsequent phases.
