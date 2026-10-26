# GitHub-driven Quarkus CI/CD

[Phase 3 acceptance evidence](PHASE3-VERIFICATION.md) records the real PR merge test.
[Phase 4 golden path](GOLDEN-PATH.md) documents self-service onboarding.

`quarkus-reference/.tekton/` owns application event-to-pipeline definitions.
`box1-gitops/platform/pipelines/tasks/` owns shared platform Tasks. Argo CD installs
those Tasks through `pipelines-ci`; Tekton's cluster resolver embeds the selected
Task definitions in each TaskRun. PipelineRun/TaskRun status records the resolved
Task specification for that execution.

## Flow

PR to `main` → immutable source checkout → Maven compile/tests → Checkstyle →
SpotBugs + FindSecBugs → GitHub validation check.

Merge/push to `main` → repeat verification → Jib build → SHA-tagged registry push
→ image digest → GitOps PR → required checks → development merge → Argo CD
reconcile → expected-runtime-digest observation → HTTPS smoke test → GitHub result.

Normal operation needs no manual PipelineRun, temporary source Secret, or cluster
mutation command. The Phase 2 manual build manifest remains a reproduction tool.

## Credentials and trust boundaries

| Task | ServiceAccount | Credentials/capability |
| --- | --- | --- |
| PR source fetch + verification | ci-test | GitHub token only in platform fetch container; no API token or push right in Maven container |
| Trusted main verification + Jib | ci-build | Namespace-scoped registry push using projected API token |
| GitOps promotion | ci-gitops | PAC App token in the promotion container; no mounted Kubernetes API token |
| Rollout observation + smoke | ci-observe | Read-only access to the one Argo Application, one Deployment, and runtime Pods |

The PAC Repository uses default-branch provenance. A PR cannot substitute its own
`.tekton` workflow before that workflow is merged into trusted `main`. PR tests
execute code from the PR, but never receive GitHub credentials or registry push
credentials in their Maven container. Source extraction and Maven bootstrapping
are platform-owned code, and the Maven URL/checksum are platform-controlled.
Shared Tasks and their cluster resolver references must remain platform-owned.
Direct Pod/PipelineRun creation in `box1-ci` is restricted operationally to trusted
platform maintainers; namespace membership alone is not a Secret boundary.

The same PAC namespace contains the registered source and GitOps repositories,
as required by this PAC version's repository-level token scoping. Both explicitly
scope issued tokens: the app to itself plus `box1-workloads-dev`, and each GitOps repository to itself.
`secret-github-app-token-scoped=false` enables those explicit Repository lists;
`secret-github-app-scope-extra-repos` stays empty. No organization-wide token is
intentionally issued. The GitHub App private key remains only in its controller
Secret; build Pods never receive it. Short-lived installation tokens are generated
for each event, without a static PAT.

`pipelines-config` owns a snapshot of the installed 1.24.1 TektonConfig spec. Its
only behavior change is the repository-level scope switch. Review this snapshot
when upgrading the Operator; the controller receives patch/update rights only
for the existing TektonConfig named `config`.

## Development promotion gate

Development desired state lives in `box1-org/box1-workloads-dev`; platform Tasks
remain in `box1-gitops`. Service repositories retain their original `deploy/`
manifests. Onboarding and image promotion create PRs in `box1-workloads-dev`.

The central promotion Task accepts a validated `application-name` (default
`quarkus-reference`) and creates a GitOps PR changing only:

- `workloads/<application-name>/kustomization.yaml`: immutable image digest.
- `workloads/<application-name>/deployment.yaml`: source SHA/build provenance.

Before merging it verifies the exact file contents, unchanged PR head, expected
App identity, current source-main SHA, and successful checks on that exact head:

- `Pipelines as Code CI / box1-phase1-smoke-`
- `Pipelines as Code CI / box1-gitops-validate-`

The manifest check renders the reference Kustomization with checksum-verified
kubectl, verifies required resources/probes, and rejects mutable/outside-registry
images. The promotion Task's explicit gate applies even where no GitHub branch
protection is configured. It does not bypass branch rules: repository owners may
add server-side required checks/reviews, and those can block the merge.

The Task's default `environment=approval` leaves a validated GitOps proposal open
for a human. The reference app explicitly selects `development`. Additional
real environment targets and their reviewer policies must be configured before
onboarding them; this phase does not create staging/production deployments.

Source releases are serialized with the Repository concurrency limit. A release
checks that its source SHA is still `main` before opening/merging a promotion;
superseded work does not deploy. A merge conflict or failed required check fails
the release and leaves evidence in GitHub/Tekton instead of forcing an update.

## Rollout and failures

Argo CD is the only application deployer. Tekton only observes Kubernetes APIs.
The observer waits up to 15 minutes for Synced/Healthy, the desired source SHA,
matching Deployment image digest, Available replicas, and a Ready Pod actually
running that digest. This prevents a healthy previous version from satisfying
the release check. Argo's normal Git polling can add a few minutes.

Then the observer tests the public TLS Route: greeting/configuration, Java 21,
health/startup/readiness, OpenAPI, Prometheus metrics, and input validation.
A smoke failure fails the release check; it does not automatically roll back.
Rollback remains a reviewed Git revert/digest promotion.

Static security checks analyze application bytecode with SpotBugs/FindSecBugs.
They do not provide an external dependency vulnerability database scan.

## Operations

Inspect `quarkus-validate-*`, `quarkus-release-*`, and `box1-gitops-validate-*` under
OpenShift Pipelines → PipelineRuns, project `box1-ci`. GitHub checks link back to
run details. Release TaskRuns separately expose build, promote, and smoke logs.

Infrastructure changes still follow the platform's manual sync boundary for
`pipelines-ci` and `pipelines-config`. Application and development image changes
reconcile automatically after their Git merges.
