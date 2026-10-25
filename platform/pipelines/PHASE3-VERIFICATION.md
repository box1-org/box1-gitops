# Phase 3 acceptance — 2026-10-24 America/New_York

The exit criterion is met: merging application code triggers a tested image
build, checked development GitOps promotion, Argo CD deployment and live smoke
verification, without a manual deployment command or manually submitted release.

## Real application change

[Application PR #1](https://github.com/box1-org/quarkus-reference/pull/1) adds
`deliveryMode: tekton-gitops` to `/api/info` and checks it in the HTTP contract.

| Stage | Commit/run | Evidence |
| --- | --- | --- |
| Intentional lint rejection | source `b319667c7604e251a468c8cfa60e343fc887b1b4`, `quarkus-validate-nvwx9` | [failed GitHub check](https://github.com/box1-org/quarkus-reference/runs/121063252730); Checkstyle rejected a wildcard import |
| Corrected PR validation | source `00eda15bdf2add831f655edeed626610e0662f1d`, `quarkus-validate-8tlr4` | [successful GitHub check](https://github.com/box1-org/quarkus-reference/runs/121063832697) |
| Validated source PR merged | `710fbe313d00ced65c8155689b6cd302804d760a` | PR #1 merged only after the exact-head validation check succeeded |
| GitHub-triggered release | `quarkus-release-r6fxm` | [successful final release check](https://github.com/box1-org/quarkus-reference/runs/121064124848) |
| Automatic development promotion | [GitOps PR #3](https://github.com/box1-org/box1-gitops/pull/3) | Automatically created and merged by the central promotion Task |
| GitOps merge | `055f39a7b566a390fbbecc6457332acddf098a76` | Argo CD reconciled this desired state without a manual sync |

On GitOps PR #3, the promotion Task waited for both required checks to succeed
on the exact head `705135f4053cff506fda13189c77e127d67ae56a`:

- [Manifest validation](https://github.com/box1-org/box1-gitops/runs/121064375744)
- [Foundation smoke check](https://github.com/box1-org/box1-gitops/runs/121064375655)

The promotion Task then verified the unchanged head, exact allowed file contents,
and current source-main SHA, and used GitHub's exact-SHA merge API. No manually
created check or override was used.

## Tests, analysis and publication

The corrected PR and main release both passed:

- Three unit tests, four Quarkus HTTP tests, four packaged-JVM integration tests:
  11 tests, zero failures/errors/skips.
- Checkstyle: zero violations on the final code.
- SpotBugs with FindSecBugs: zero bug instances/errors.

PR validation used `ci-test`, returned `image-digest=not-published`, had no
projected Kubernetes API token volume, and did not receive the GitHub token in
the Maven container. The negative lint run failed before any publication stage.

The main release published this SHA-tagged image:

```text
registry.apps.ocp.box1.org/box1-ci/quarkus-reference:710fbe313d00ced65c8155689b6cd302804d760a
```

It emitted and promoted this immutable digest:

```text
sha256:624d4f832087a651ce03b99b9a07a4a1c3c1694dc176f8eecc3c6ae6ac44dbc5
```

The actual PAC-generated release token was inspected through GitHub's API and
listed exactly `box1-org/quarkus-reference` and `box1-org/box1-gitops`.
No token value was printed. GitOps's own Repository scope remains itself only.

## Automatic rollout and smoke

The three release TaskRuns succeeded with distinct identities:

| TaskRun | ServiceAccount |
| --- | --- |
| quarkus-release-r6fxm-build | ci-build |
| quarkus-release-r6fxm-promote | ci-gitops |
| quarkus-release-r6fxm-smoke | ci-observe |

`ci-observe` has read-only access to the reference Argo Application, Deployment
and Pods; an impersonated check confirmed Deployment patch permission is denied.
It waited for Argo Synced/Healthy, the expected source annotation, Deployment
image, Available replicas and a Ready Pod actually running the promoted digest.
It did not force an Argo refresh or write a workload resource.

The observer passed real HTTPS Route checks for greeting/configuration, Java 21,
health/startup/readiness, OpenAPI, Prometheus metrics, and invalid-name HTTP 400.
The live response at https://quarkus-reference.apps.ocp.box1.org/api/info was:

```json
{"name":"quarkus-reference","version":"1.0.0-SNAPSHOT","javaVersion":21,"deliveryMode":"tekton-gitops"}
```

The Deployment source annotation matched `710fbe313d00ced65c8155689b6cd302804d760a`
and its internal-registry image reference matched the digest above. All platform
Argo Applications, including `pipelines-config`, remained Synced / Healthy.

## Reusable configuration and approval policy

Application `.tekton/` definitions reference GitOps-managed central Tasks through
the cluster resolver. `platform/pipelines/tasks/` contains the Maven/Jib,
promotion, manifest-validation and rollout/smoke Tasks. PAC uses default-branch
provenance and reports the resulting statuses to GitHub.

Development promotion explicitly opts into automatic merging after required
checks. The central promotion Task defaults to `environment=approval`, which
leaves the GitOps PR open for review. This phase creates only the reference
application's development target; additional real environments need their own
target manifests and reviewer policies. The Task enforces its own required-check
gate and honors any GitHub branch rules; this rollout did not add server-side
branch protection or configure production deployments.

An earlier bootstrap release, `quarkus-release-pkvfb`, also completed the full
flow through [GitOps PR #2](https://github.com/box1-org/box1-gitops/pull/2).
See [AUTOMATION.md](AUTOMATION.md) for operating details and failure behavior.
