# Box1 CI/CD foundation

See [rollout evidence and remaining dependencies](STATUS.md) for live verification.

Developer Hub scaffolds applications, Tekton tests/builds/pushes images and proposes
GitOps changes, and Argo CD alone reconciles application workloads. No application
pipeline should run `oc apply`, `kubectl apply`, or `argocd app sync`.

## Layout and ownership

- `operator/`: OLM Subscription in the existing global `openshift-operators`
  OperatorGroup. Do not add another OperatorGroup there.
- `ci/`: `box1-ci`, Pipelines as Code Repository for `box1-org/box1-gitops`,
  separate test/build/GitOps identities, and namespace-scoped registry push access.
- `../../.tekton/phase1-smoke.yaml`: GitHub push/PR smoke check. It intentionally
  does not build an application or use write credentials.
- Both child Applications require manual synchronization. Operator readiness is
  a real boundary; sync waves on child Application objects are insufficient.

Observed on 2026-10-24: OpenShift `5.0.0-rc.7`; Pipelines package
`openshift-pipelines-operator-rh`, channel `pipelines-1.24`, head
`openshift-pipelines-operator-rh.v1.24.1`, catalog `redhat-operators` in
`openshift-marketplace`. The catalog supports AllNamespaces installation.
`startingCSV` selects the initial release; later updates need InstallPlan review.
Catalog availability does not establish vendor support for this OpenShift RC.

## Rollout

Run commands from the repository root with an authenticated cluster context.
Publish the repository changes first. Bootstrap the existing `box1-root` manifest
if it is absent, then wait for its child Applications to appear:

```sh
kubectl apply -f box1-root/application.yaml
kubectl -n openshift-gitops get applications
kubectl -n openshift-gitops patch application pipelines-operator --type=merge \
  -p '{"operation":{"sync":{"revision":"main","prune":false}}}'
kubectl -n openshift-operators get subscription openshift-pipelines-operator
kubectl -n openshift-operators get installplan
```

Inspect the Subscription's referenced InstallPlan and its CSV list before
approving that exact plan; do not bulk-approve plans in the shared namespace.
Wait for the CSV to succeed and Pipelines/PAC to become ready:

```sh
kubectl get tektonconfig config
kubectl -n openshift-pipelines get deployments,route
kubectl wait --for=condition=Established crd/pipelineruns.tekton.dev --timeout=120s
kubectl wait --for=condition=Established crd/repositories.pipelinesascode.tekton.dev --timeout=120s
kubectl -n openshift-gitops patch application pipelines-ci --type=merge \
  -p '{"operation":{"sync":{"revision":"main","prune":false}}}'
```

After the first sync creates `box1-ci`, validate subsequent changes with
`kubectl apply --dry-run=server -k platform/pipelines/ci`. A server dry run of
a new Namespace does not create it for the other resources in the same request.

Pipelines as Code is enabled by default by this Operator. Verify
`spec.platforms.openshift.pipelinesAsCode.enable` in the generated TektonConfig
rather than creating a competing TektonConfig with guessed installation defaults.
If someone has explicitly disabled it, review the existing configuration before
changing its ownership. Do not mask missing CRDs with SkipDryRunOnMissingResource.

## Dedicated GitHub App

Create an organization-owned App at
https://github.com/organizations/box1-org/settings/apps/new, separate from the
Developer Hub sign-in/catalog App. Suggested name: `Box1 Pipelines` (names must be
unique on GitHub). Use the OpenShift console URL as homepage. Read the actual
webhook endpoint rather than guessing it:

```sh
kubectl -n openshift-pipelines get route pipelines-as-code-controller \
  -o jsonpath='{.spec.host}{"\n"}'
```

Verified endpoint: `https://pipelines-as-code-controller-openshift-pipelines.apps.ocp.box1.org`.
Use that HTTPS endpoint as the active webhook URL. Following Red Hat's manual App
setup, grant repository Checks, Contents, Issues, and Pull requests read/write,
Metadata read, and organization Members read. Subscribe to Check run, Check suite,
Commit comment, Issue comment, Pull request, and Push. Install the App initially
on `box1-gitops` only; include new application repositories when onboarding them.
The CI namespace must be restricted to trusted platform maintainers.

Keep the App ID, PEM private key, and generated webhook secret outside Git. Have
the platform secret manager create Opaque Secret `pipelines-as-code-secret` in
`openshift-pipelines` with these exact keys:

| Key | Value |
| --- | --- |
| `github-application-id` | App numeric ID |
| `github-private-key` | Full multiline PEM text |
| `webhook.secret` | Same random value configured in GitHub |

For private local files, the equivalent command avoids values in shell history
and command-line arguments (files contain the values without extra newlines):

```sh
kubectl -n openshift-pipelines create secret generic pipelines-as-code-secret \
  --from-file=github-application-id=/secure/path/app-id \
  --from-file=github-private-key=/secure/path/app.pem \
  --from-file=webhook.secret=/secure/path/webhook-secret
```

Do not export the live Secret into the repository. Do not reuse the Developer
Hub App private key, client secret, or backend token for this integration.

## Registry and GitOps credential boundaries

The existing managed registry is `image-registry.openshift-image-registry.svc:5000`
inside the cluster and `registry.apps.ocp.box1.org` externally. `ci-build` may push
only into its `box1-ci` image project via `system:image-builder`. Build tooling
must explicitly authenticate to the registry using its projected service account
token or managed registry credential. Do not assume a Docker config appears in
HOME. Preserve TLS verification; use the cluster's injected service CA for the
internal service endpoint. No privileged SCC is granted here; select and validate
an OpenShift-compatible build task in the Quarkus phase.

`ci-test` and `ci-gitops` disable automatic Kubernetes token mounting. None of
these accounts receives application Deployment/Route/Service write permissions.
Future runtime namespaces need a separate `system:image-puller` binding for their
runtime ServiceAccount to pull from `box1-ci`; no wildcard pull access is added.

GitOps credentials use the dedicated Pipelines App's temporary installation
credentials. PAC creates a new `{{git_auth_secret}}` for each run; its
`git-provider-token` key is available to trusted tasks through an explicit
`secretKeyRef`. There is no static `gitops-writer` Secret or PAT to renew.
`.tekton/gitops-auth-check.yaml` validates write access to `box1-org/box1-gitops`
on pushes to `main`, using `ci-gitops`. It runs only inline platform-owned code,
does not clone or run application code, and never prints the token. It proves
Contents write permission by resubmitting an existing README blob to the Git
object API and checking the identical SHA; no branch or file is changed. PR smoke
checks continue to use `ci-test` without mounting this credential.

This works for Phase 1 because the event repository is itself `box1-gitops`.
Future application release pipelines require an explicit, reviewed cross-repo
token-scope configuration for `box1-org/box1-gitops`, with a matching PAC
Repository registration in the trusted namespace and an App installation covering
both repositories. Do not assume this is already enabled. Follow the installed
PAC version's scope settings; keep any global extra-repository list empty and
verify the issued token's actual access before onboarding a release pipeline.
Mount tokens only in the GitOps update task, never in untrusted build/PR steps.
Tokens expire; long-running tasks must finish within the issued token lifetime.

Kubernetes ServiceAccounts are not a Secret-access boundary for someone who can
create arbitrary Pods/PipelineRuns in the same namespace. Before onboarding
application contributors or executing arbitrary PR code, provision separate
untrusted-test and trusted-release namespaces/controllers or enforce equivalent
admission policy. The shared `box1-ci` namespace here is for platform-maintainer
smoke testing only. Provenance `default_branch` keeps PR pipeline definitions
from replacing the smoke check; it does not make arbitrary PR code safe to run
with a mounted credential.

Trusted release builds must publish a result containing `sha256:...`, then open
a GitOps PR setting the workload image to `registry/path@sha256:...`. Argo CD
reconciles the reviewed desired state. Never promote a PR image automatically,
pass a mutable tag as desired state, or commit an image update back into the
application repository and create a CI loop.

## Acceptance evidence

After the App is installed and its Secret is provisioned:

1. Commit a harmless change on a branch and open a PR targeting `main`. The smoke
   definition must already be present on `main` because of default-branch
   provenance. A PR without the App installation cannot satisfy this test.
2. In the App's advanced webhook deliveries, verify a valid signed PR/push event
   returns HTTP 2xx and record its delivery ID. Ping alone is insufficient.
3. Verify `kubectl -n box1-ci get pipelineruns` shows the matching SHA, a successful
   `Succeeded` condition, and the `ci-test` account. Inspect its TaskRun logs.
4. Verify GitHub shows a successful check for **box1-phase1-smoke** on the same PR
   head commit. Push another commit and confirm a new check/run for that SHA.
5. Verify the test SA cannot deploy or push images; verify the build SA can push
   only to `box1-ci`. Registry authentication and an actual build/push digest
   require a separate real build test in the Quarkus phase.

A manually created PipelineRun proves Tekton execution only. It does not prove
webhook signature validation, GitHub App installation, or PR check reporting.
Do not mark Phase 1 complete without GitHub event-to-check evidence.

## References

- [Red Hat golden path foundation, September 17, 2026](https://developers.redhat.com/articles/2026/09/17/build-unified-cicd-control-plane-red-hat-developer-hub)
- [Red Hat golden path template, September 25, 2026](https://developers.redhat.com/index.php/articles/2026/09/25/build-golden-path-cicd-workflows-red-hat-developer-hub)
- [Red Hat Pipelines as Code manual GitHub App setup](https://docs.redhat.com/en/documentation/red_hat_openshift_pipelines/1.22/html-single/pipelines_as_code/index)
- [Pipelines as Code Repository settings](https://pipelinesascode.com/docs/api/settings/)
