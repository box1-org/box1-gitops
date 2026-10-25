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

## GitHub acceptance completed

The Phase 1 event-to-check exit criterion is met. Dedicated GitHub App
`Box1 Pipelines` (`box1-pipelines`) is installed on `box1-org`; the user provisioned
`openshift-pipelines/pipelines-as-code-secret` with the three expected keys.
The installation currently selects all organization repositories. Tokens used by
the phase-one pipelines remain scoped to their event repository, `box1-gitops`.

Signed GitHub webhook deliveries were accepted with HTTP 202, and PAC created
matching PipelineRuns and reported successful GitHub checks:

| Event | Commit | PipelineRun | GitHub check |
| --- | --- | --- | --- |
| main push | `06adc2ec0ba0650df174c52d751f1916a001a06c` | `box1-phase1-smoke-744gs` | [success](https://github.com/box1-org/box1-gitops/runs/121054239862) |
| main push, token write probe | `06adc2ec0ba0650df174c52d751f1916a001a06c` | `box1-gitops-auth-c8mmh` | [success](https://github.com/box1-org/box1-gitops/runs/121054239878) |
| PR #1 opened | `77c2a5cf9145101901fd2532d078cea25fe744a5` | `box1-phase1-smoke-24z89` | [success](https://github.com/box1-org/box1-gitops/runs/121054060331) |
| PR #1 second commit | `9e356468ce84caa758efbbfd084630be47a26a7a` | `box1-phase1-smoke-2b2sr` | [success](https://github.com/box1-org/box1-gitops/runs/121054358091) |

Webhook evidence:

| Event | Delivery ID | GUID | Response |
| --- | --- | --- | --- |
| main push | `3850214114349563904` | `951af4da-d01c-11f1-98a0-5f296668fb14` | 202 |
| PR opened | `3850213998098120704` | `7470d790-d01c-11f1-8cce-e781324214cf` | 202 |
| PR synchronize | `3850214190992072704` | `aa213240-d01c-11f1-926d-7703c614b385` | 202 |

[Draft acceptance PR #1](https://github.com/box1-org/box1-gitops/pull/1) is left
open for review; its documentation-only changes do not need to be merged to
satisfy the test. Neither PR run mounted the GitOps credential. Main-only
`gitops-auth-check.yaml` uses `ci-gitops` and PAC's generated short-lived token.
Its write probe resubmitted the existing README Git blob, verified the identical
SHA, and changed no branches, files, or workloads. No static bot PAT or
`gitops-writer` Secret is required for this phase.

Historical `box1-gitops-auth-cnkh6` failed because the first probe relied on a
repository metadata permissions field absent from the App-token response.
The corrected check verifies the Contents write API directly and passed.

## Subsequent phases

Registry RBAC was verified. Actual authenticated image push and digest output
await the Quarkus build task; RBAC checks alone do not prove a working push.
Application scaffolding, Quarkus build/test, GitOps image PR automation, runtime
pull access, and Argo-managed application deployment remain subsequent work.
Cross-repository token scope for application release pipelines is not enabled by
this foundation and must be explicitly configured and tested in the trusted
release namespace. See [README.md](README.md) for credential boundaries.
