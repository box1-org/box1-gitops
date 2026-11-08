# Quarkus golden path

Developer Hub **Create → Create Quarkus Service** loads
[`box1-org/box1-templates`](https://github.com/box1-org/box1-templates).
The platform-owned `quarkus-rest-service` template uses the installed
`fetch:template`, `box1:repository:ensure`, `box1:catalog:submit`,
`box1:development:provision`, `platform`, `build`, `promote` and `verify`, and
`box1:catalog:verify` actions (template 1.2.0). Authentication uses the Developer Hub GitHub App;
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

One automatically validated, development-only onboarding PR in `box1-workloads-dev`
adds only a new `applications/<service>.yaml` and `workloads/<service>/` directory.
The `box1-workloads-dev` parent discovers the new Application and it reconciles
automatically. Its resources include:

- Namespace, restricted runtime ServiceAccount, zero-replica Deployment, startup,
  readiness/liveness probes, hashed ConfigMap, Service, and HTTPS Route.
- PAC Repository in `box1-ci`, trusted default-branch provenance, serialized
  releases, and short-lived token scope restricted to itself plus `box1-workloads-dev`.
- A registry image-puller RoleBinding for that runtime ServiceAccount.
- Per-service read-only observation Roles/Bindings for `ci-observe`.

The Kustomization deliberately omits a global `namespace` transformer: runtime
objects and the ConfigMap generator specify their namespace explicitly, while
PAC and observation RBAC retain `box1-ci` / `openshift-gitops` namespaces.

The initial Deployment has zero replicas and a non-runnable zero image digest.
No reference-app image or unbuilt application image runs under the new identity.
The workflow merges the allowlisted onboarding PR only after its exact-head
required checks pass. It requests the Argo sync, then waits only for the active
Namespace, the `ci-build` ServiceAccount and its registry push binding before
creating the first PipelineRun, reusing `box1-quarkus-maven`. While the build runs,
it waits for the sync and observes the required ServiceAccounts, registry and
observer bindings, PAC Repository, synced Argo Application and initial Deployment.
Promotion does not start until those checks have passed. A source-only, one-hour GitHub App
Contents-read token is persisted in a Secret before PipelineRun creation and
removed after the build. No extra source commit or manual sequencing is needed.

The first immutable image is proposed in a second checked development PR,
merged automatically by the Hub App, and deployed by an explicit Argo sync request. Completion requires
the expected image, an available current Deployment generation, Argo health,
public readiness, the original source SHA in `/api/info`, and catalog
registration. The durable `rhdh/box1-onboard-<service>` status record and renewable
Lease support partial-failure resumption without duplicate resources. Task
outputs include source, catalog, initial CI, deployment and Argo links.

Subsequent main pushes use the existing shared promotion Task. It accepts `application-name` (defaulting to the existing
reference service), verifies its source main SHA, and changes exactly that
service's digest/provenance files. Its first successful promotion activates the
Deployment at one replica. The normal exact-head check gate then merges the
development GitOps PR. If a required check reports the Pipelines as Code
"pipelinerun start failure" (a transient GitHub 404 in PaC 0.50.x, box1-docs#64),
the gate rerequests that check-run up to twice instead of failing the release;
any other failed check still fails it. The parameterized observer verifies that service's Argo
state, runtime digest, source annotation, public endpoints, and `/api/info.gitRef`.
Promotion and smoke accept the Argo Application as converged when it is
`Synced`, or `OutOfSync` only because old kustomize-generated ConfigMaps
(`<name>-<10-char hash>`) await pruning. A `configMapGenerator` change leaves
that leftover, and workload Applications do not auto-prune (box1-docs#42). Any
other out-of-sync resource, an unhealthy Application or a wrong revision still
fails the release. The orphans are listed in the Task log and remain until
someone prunes them.
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

Kubernetes, Argo CD, Tekton and Topology use the configured live read-only
connections. The separate onboarding runtime ServiceAccount has state/lease and
initial-build permissions plus readiness reads; it cannot mutate workload
Deployments, Namespaces, Applications or RBAC. Its projected token rotates
automatically. The GitHub App performs repository creation and checked GitOps
merges. Runtime source and tests live in `box1-templates/plugins/box1-onboarding`;
GitOps transports the module using the generated ConfigMap.

## Validation and operations

See `box1-templates/VERIFICATION.md` for the real scaffolder task, onboarding PR,
first release, and live Route evidence. Current zero-touch acceptance and replay
evidence is in `box1-templates/verification/shipping-service/README.md`. The template repository's `npm run
validate` renders multiple names (including the maximum length) with Nunjucks, validates both Kustomizations,
checks cross-namespace identities and pipeline parameters, and rejects unsafe
names. `ACTION_SCHEMAS=<exported live actions JSON>` additionally checks action
inputs against the installed Hub action schemas.

Both Apps must remain installed on all new repositories. Shared CI accounts and
Tasks are prerequisites; onboarding does not clone their definitions. Platform
maintainers review onboarding permissions. The shared namespace trust boundary
and promotion gate remain as described in [AUTOMATION.md](AUTOMATION.md).

## Earlier orders service milestone

The complete creation → build → deployment → REST PR → redeployment → image
rollback demonstration passed for `orders-service` in `orders-service-dev`.
Creation used the Hub API at the user's request. Source PR #1 and GitOps
onboarding/promotion/rollback PRs #8–#11 retain the audit trail. The service is
left on the baseline image after the successful GitOps rollback; source main
retains the endpoint update.

[Milestone evidence and live snapshots](https://github.com/box1-org/box1-templates/blob/main/MILESTONE-DEMO.md).

The Workstream 3 regression baseline is captured separately in
`box1-templates/verification/shipping-service/orders-regression.json`. Its
Deployment spec, UID, generation, image, Application spec and Pod UIDs remained
unchanged throughout shipping-service onboarding.

Development Applications and `workloads/<service>/` now live in
`box1-org/box1-workloads-dev`. The platform root installs the workload parent
Application. Generated source repositories keep their original `deploy/` files.

## Virtual machine workload profile (RHEL 10 image mode)

Tracked in box1-docs#55, based on the box1-docs#46 prototype. A workload opts in with the Namespace label `box1.org/workload-profile: virtual-machine`. Without the label, a workload uses the `service` rules above, unchanged.

`box1-gitops-validate` checks VM workloads with these rules:

- **Required kinds:** Namespace, ServiceAccount (the updater), a `kubernetes.io/service-account-token` Secret with no data in Git, and exactly one VirtualMachine named after the workload.
- **Forbidden:** Deployments, StatefulSets, DaemonSets, Pods, container `image:` fields, and `dataVolumeTemplates`. A DataVolume spec is immutable, so a placeholder source would never be replaced.
- **VirtualMachine annotations:** it records `box1.org/os-image-digest` and `box1.org/source-revision`.
- **Update disks:** the VM attaches the `serviceca` and `regtoken` disks used for `bootc upgrade`.
- **Unbuilt** (zero OS digest): `runStrategy: Halted`, and the kustomization does not list `datavolume.yaml`.
- **Promoted:** exactly one root DataVolume `<name>-root`, pulling `box1-ci/<name>-disk@sha256:…` with `pullMethod: node`.
- **Secrets other than the token** may hold only SSH public keys. Admin keys reach the guest at runtime through KubeVirt `accessCredentials` (qemu-guest-agent).

Delivery uses central Tasks:

| Task | Purpose | Service account |
| --- | --- | --- |
| `box1-bootc-build` | Privileged buildah. Uses the build secrets `redhat-registry-pull` and `etc-pki-entitlement`. | `ci-bootc-check` for PRs, `ci-bootc-release` for releases |
| `box1-bootc-disk` | bootc-image-builder to a containerDisk `box1-ci/<name>-disk`. The installed system tracks `box1-ci/<name>:<channel>`. | `ci-bootc-release` |
| `box1-gitops-promote` with `workload-profile: virtual-machine` | Day 2: edits only the VM annotations, which does not restart the VM. First promotion: also sets the disk digest, adds `datavolume.yaml` and sets `runStrategy: Always`. | `ci-gitops` |
| `box1-bootc-channel` | After the merge and sync, moves `:<channel>` to exactly the promoted manifest, then reads it back to confirm. | `ci-bootc-release` |
| `box1-vm-smoke` | Checks that Argo is Synced and Healthy, the digest and source are recorded, the VM is Ready, and the agent is connected. | `ci-observe` |

The guest applies an approved OS image deliberately with `sudo bootc upgrade --apply`.

Contract tests:

```sh
BOX1_WORKLOADS_DEV=/path/to/box1-workloads-dev python3 platform/pipelines/tasks/test-gitops-validate.py
python3 platform/pipelines/tasks/test-gitops-promote.py
```
