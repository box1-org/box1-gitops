# Quarkus golden path

Developer Hub **Create → Create Quarkus Service** loads
[`box1-org/box1-templates`](https://github.com/box1-org/box1-templates).
The platform-owned `quarkus-rest-service` template uses the installed
`fetch:template`, `publish:github`, `publish:github:pull-request`, and
`catalog:register` actions. Authentication uses the Developer Hub GitHub App;
no personal token is requested from developers.

The form takes a unique DNS-safe service/repository name, description, catalog
owner (imported User or Group), and private/public repository visibility.
Organization, registry, Java package, development environment, and ingress domain
are platform choices. Reserved platform/OpenShift namespace names are rejected.
Repository access follows the organization's existing access policy; a catalog
ownership relation does not itself grant GitHub repository permissions.

## Generated application

The application contains Quarkus 3 / Java 21 / Maven, REST, health, OpenAPI,
Micrometer, unit/HTTP/packaged tests, Checkstyle/FindSecBugs, Jib configuration,
embedded Git SHA in `/api/info`, catalog metadata, ownership metadata, a README,
Maven wrapper, smoke script, and `.tekton/` PR/release definitions. It also has a
`deploy/` onboarding snapshot for inspection and offline Kustomize rendering.
The authoritative desired state lives in GitOps after onboarding.

## Generated GitOps proposal

The development namespace and Route use `<service>-dev`; the repository, image,
Deployment, and Argo Application keep `<service>` as their identity.

One reviewed onboarding PR adds only a new `applications/<service>.yaml` and
`workloads/<service>/` directory. The new app is discovered by the existing
app-of-apps and reconciles automatically. Its resources include:

- Namespace, restricted runtime ServiceAccount, zero-replica Deployment, startup,
  readiness/liveness probes, hashed ConfigMap, Service, and HTTPS Route.
- PAC Repository in `box1-ci`, trusted default-branch provenance, serialized
  releases, and short-lived token scope restricted to itself plus `box1-gitops`.
- A registry image-puller RoleBinding for that runtime ServiceAccount.
- Per-service read-only observation Roles/Bindings for `ci-observe`.

The Kustomization deliberately omits a global `namespace` transformer: runtime
objects and the ConfigMap generator specify their namespace explicitly, while
PAC and observation RBAC retain `box1-ci` / `openshift-gitops` namespaces.

The initial Deployment has zero replicas and a non-runnable zero image digest.
No reference-app image or unbuilt application image runs under the new identity.
After the onboarding PR merges and Argo finishes, the first application change
starts delivery. The initial repository-creation webhook precedes registration
and is not assumed to be replayed. An empty Git commit can start acceptance
without changing code; the generated README includes that command.

The shared promotion Task accepts `application-name` (defaulting to the existing
reference service), verifies its source main SHA, and changes exactly that
service's digest/provenance files. Its first successful promotion activates the
Deployment at one replica. The normal exact-head check gate then merges the
development GitOps PR. The parameterized observer verifies that service's Argo
state, runtime digest, source annotation, public endpoints, and `/api/info.gitRef`.
The validator renders every workload target and accepts a zero digest only for
a zero-replica onboarding Deployment.

Tekton performs no application apply/patch. Developers write code; Tekton owns
builds; Argo CD owns deployments; Developer Hub presents the workflow.

## Hub plugin configuration

Git owns the required bundled GitHub scaffolder backend module in
`platform/developer-hub/dynamic-plugins.yaml`. The Extensions installer adapter
merges UI plugin choices by package name, with required platform entries taking
precedence. Other UI choices remain on the PVC. The App is installed for all
organization repositories and grants Administration/Contents/Pull requests write
permissions for repository creation and GitOps proposals.

A restart also exposed previously enabled Kubernetes and Argo CD plugins with
incomplete default connection placeholders. App configuration clears those
connection lists so the Hub starts. Their read-only cluster/UI connections remain
a separate configuration task; catalog annotations are already generated.

## Validation and operations

See `box1-templates/VERIFICATION.md` for the real scaffolder task, onboarding PR,
first release, and live Route evidence. The template repository's `npm run
validate` renders multiple names (including the maximum length) with Nunjucks, validates both Kustomizations,
checks cross-namespace identities and pipeline parameters, and rejects unsafe
names. `ACTION_SCHEMAS=<exported live actions JSON>` additionally checks action
inputs against the installed Hub action schemas.

Both Apps must remain installed on all new repositories. Shared CI accounts and
Tasks are prerequisites; onboarding does not clone their definitions. Platform
maintainers review onboarding permissions. The shared namespace trust boundary
and promotion gate remain as described in [AUTOMATION.md](AUTOMATION.md).

## Orders service milestone

The complete creation → build → deployment → REST PR → redeployment → image
rollback demonstration passed for `orders-service` in `orders-service-dev`.
Creation used the Hub API at the user's request. Source PR #1 and GitOps
onboarding/promotion/rollback PRs #8–#11 retain the audit trail. The service is
left on the baseline image after the successful GitOps rollback; source main
retains the endpoint update.

[Milestone evidence and live snapshots](https://github.com/box1-org/box1-templates/blob/main/MILESTONE-DEMO.md).
