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

## VM instance workload profile (`vm-instance`)

Tracked in box1-docs#139 (sub-issue of #126). One bootc OS image repository (the
*source*, for example `site-gateway-os`) boots many VM instances. Each instance has its
own `workloads/<instance>/` directory, namespace, VirtualMachine and Argo Application,
and pins its own approved digest. A workload opts in with the Namespace label
`box1.org/workload-profile: vm-instance`. The `service` and `virtual-machine` rules
above are unchanged.

### Source allowlist

The allowed sources are the tuple `VM_INSTANCE_SOURCES` near the top of the
`box1-gitops-validate` script (`tasks/gitops-validate.yaml`). Each entry is a bare
`box1-org` repository name; its disk image is `box1-ci/<source>-disk`. It currently
holds `site-gateway-os`. Adding a source is a reviewed `box1-gitops` PR that edits the
tuple, so the allowlist changes together with, and is reviewed like, the validator.

### Validation rules

`box1-gitops-validate` applies these checks, then every `virtual-machine` rule above,
with the root disk expected from `box1-ci/<source>-disk` instead of `<name>-disk`:

| Rule | Failure message (prefix) |
| --- | --- |
| Exactly one VirtualMachine, named after the instance directory | `Exactly one VirtualMachine must be named after the instance <instance>; found …` |
| The VM records its source in the annotation `box1.org/source-image` | `VM instance must record its source OS image repository in box1.org/source-image exactly once` |
| The source is on the allowlist | `Source image <source> is not on the vm-instance allowlist (VM_INSTANCE_SOURCES …)` |
| No inline `userData`, `userDataBase64`, `networkData` or `networkDataBase64`, in any cloud-init volume | `VM instances must not inline <key>; reference the <instance>-cloud-init Secret with cloudInitNoCloud.secretRef` |
| Exactly one `cloudInitNoCloud` volume | `VM instance needs exactly one cloudInitNoCloud volume with secretRef.name: <instance>-cloud-init` |
| It references the Secret `<instance>-cloud-init` | `cloudInitNoCloud must use secretRef.name: <instance>-cloud-init` |
| That Secret (and any `networkDataSecretRef`) is not rendered from Git | `Secret <name> must be created outside Git, not rendered from it: …` |
| No ConfigMap (including `<instance>-site`) holds a credential-looking key, a PEM private key, or a value that assigns one (`PASSWORD=…`, `secret: …`) | `ConfigMap <name> must not hold credentials; found …` |
| The DataVolume is named `<instance>-root` | `Root DataVolume must be named <instance>-root; found …` |
| Promoted: one DataVolume from `docker://…/box1-ci/<source>-disk@sha256:<non-zero>` with `pullMethod: node`; a tag, the zero digest or another source's disk fails | `Root DataVolume must pull the digest-pinned <source>-disk image` |
| Unbuilt (zero OS digest): `runStrategy: Halted` and no DataVolume | `Unbuilt virtual machines must stay Halted`, `Unbuilt virtual machines must not create their DataVolume yet` |
| Secrets other than the updater token hold only SSH public keys (the `virtual-machine` rule) | `Only SSH public keys may be stored in Secrets` |

box1-docs#138 adds the remaining rules of the #140 instance bundle specification
(`box1-docs/runbooks/vm-cloud-init-identity.md`), checked after the rules above:

| Rule | Failure message (prefix) |
| --- | --- |
| The only cloud-init volume (`cloudInitNoCloud` or `cloudInitConfigDrive`) is named `cloudinitdisk` | `The only cloud-init volume must be named cloudinitdisk` |
| It is `cloudInitNoCloud` with exactly `secretRef.name: <instance>-cloud-init`: no `networkDataSecretRef` or other keys | `cloudInitNoCloud must set only secretRef.name: <instance>-cloud-init` |
| A disk named `cloudinitdisk` exists | `VM instance needs a disk named cloudinitdisk` |
| No `serial` (firmware SMBIOS or disk) starts with `ds=`, which would point cloud-init at another datasource | `VM instances must not set a ds= SMBIOS or disk serial` |
| `accessCredentials` use `qemuGuestAgent` for `cloud-user` only; `noCloud` and `configDrive` propagation are refused | `accessCredentials must use qemuGuestAgent…`, `accessCredentials may only propagate keys to cloud-user…` |
| No rendered Secret has a `userdata`, `userData`, `networkdata` or `networkData` key | `Secret <name> must not hold cloud-init <key> in Git` |
| Exactly one ConfigMap `<instance>-site`, labelled `box1.org/instance: <instance>`, without `binaryData` | `VM instance needs exactly one ConfigMap <instance>-site…`, `…must be labelled box1.org/instance: <instance>`, `…must not have binaryData` |
| Its keys are only `siteId`, `keycloakClientId`, `keycloakTokenUrl` (required) and `assetServiceUrl`, `kafkaBootstrapServers`, `otlpEndpoint` (optional), each a single-line value matching the #140 pattern | `ConfigMap <instance>-site may only hold…`, `…must set <key>`, `…does not match the #140 pattern…` |

The #140 patterns: `siteId` `^[a-z][a-z0-9_]{1,62}$`; `keycloakClientId`
`^[a-z][a-z0-9-]{1,62}$`; `keycloakTokenUrl` and `assetServiceUrl` `https://host[:port][/path]`;
`otlpEndpoint` `http(s)://host[:port][/path]`; `kafkaBootstrapServers` `host:port[,host:port…]`.
URL paths allow only `A-Za-z0-9._%+:-` and `/`, so user info (`@`), queries (`?`), spaces,
quotes and `$` are refused. The assembly script in box1-docs applies the same allowlist.

The six `<instance>-site` keys above are exempt from the key-name test below (the #140
key `keycloakTokenUrl` contains the word `token`); their values are still checked, and
every other ConfigMap keeps the key-name test.

Credential-looking ConfigMap keys are split into words on camelCase, `-`, `_` and `.`;
a key containing the word `secret`, `password`, `passwd`, `pwd`, `passphrase`,
`token`, `key`, `apikey`, `privatekey`, `credential` or `kubeconfig` (or a plural)
fails, and so does any value containing `password`, `passwd`, `pwd`, `secret`, `token`,
`api_key`/`apikey` or `credential` followed by `:` or `=` and a value. So
`keycloakUrl` and `keycloakClientId` pass, and `clientSecret`, `admin_password`,
`apiKey` and `sshKey` fail.

The installed OpenShift Virtualization 5.0.0 `VirtualMachine` CRD (`kubevirt.io/v1`)
has `cloudInitNoCloud.secretRef` and `networkDataSecretRef` (checked read-only on
2026-11-08 for box1-docs#139).

### Instance bundle contract (for #138 and #140)

`workloads/<instance>/` holds the `virtual-machine` bundle files, with these
differences:

- `namespace.yaml`: the label `box1.org/workload-profile: vm-instance`.
- `virtualmachine.yaml`: `metadata.name: <instance>`, the annotation
  `box1.org/source-image: <source>` (a metadata annotation, beside
  `box1.org/os-image-digest`), and a disk plus volume `cloudinitdisk` with
  `cloudInitNoCloud.secretRef.name: <instance>-cloud-init`.
- `datavolume.yaml`: `metadata.name: <instance>-root`, with the url
  `docker://image-registry.openshift-image-registry.svc:5000/box1-ci/<source>-disk@sha256:000…`
  until the first promotion. As for `virtual-machine`, the file exists from onboarding
  but is not listed in `kustomization.yaml` until then.
- The non-secret ConfigMap `<instance>-site` (siteId and endpoints, the #140 keys
  above). Required since box1-docs#138: the cloud-init assembly script reads it. Use a
  plain resource, or `generatorOptions.disableNameSuffixHash: true`, so its name is stable.
- The `<instance>-cloud-init` Secret is never in Git. It must exist before the first
  promotion starts the VM; otherwise the VM cannot start and `box1-vm-smoke` fails.

### Promotion contract (for #138)

`box1-gitops-promote` takes `workload-profile: vm-instance` and a new
`instance-name` parameter (default empty; it must be empty for the other profiles):

- `application-name` is the **source** repository. Its `main` must still equal
  `revision`, both before the PR and before the merge, as for every profile.
- `instance-name` is the workload directory, the VirtualMachine, the Argo Application
  that is synced, and the name in the branch `promote/<instance>/…` and the PR title.
- Edited files: `workloads/<instance>/virtualmachine.yaml` always; on the first
  promotion also `datavolume.yaml` (zero digest to `disk-digest`, still from
  `box1-ci/<source>-disk`) and `kustomization.yaml` (adds `datavolume.yaml`), and the
  VM goes from `Halted` to `Always`. The VM must already carry
  `box1.org/source-image: <application-name>`.
- Day 2 changes only the instance's annotations (`os-image-digest`, `source-revision`,
  `build-pipelinerun`), exactly like `virtual-machine`. **The DataVolume digest is not
  swapped on day 2**, although the #139 prompt proposed it: CDI's DataVolume admission
  webhook validates updates and DataVolume specs are treated as immutable here (see the
  `virtual-machine` first-promotion comment), so a changed url would fail the Argo sync
  without re-imaging the disk. Recorded as a decision in
  `box1-docs/agent-runs/139-gitops-vm-instance/`; how an instance moves to a new digest
  is #141.
- Other instances of the same source are never read or changed. One release promotes
  one instance; promoting several instances means one promote Task per instance.

Example (inside a source repository's release Pipeline):

```yaml
    - name: promote-site-west
      taskRef:
        resolver: cluster
        params:
        - name: kind
          value: task
        - name: name
          value: box1-gitops-promote
        - name: namespace
          value: box1-ci
      params:
      - name: revision
        value: "$(params.revision)"
      - name: image-digest
        value: "$(tasks.build.results.image-digest)"
      - name: git-auth-secret
        value: "$(params.git-auth-secret)"
      - name: environment
        value: development
      - name: pipeline-run
        value: "$(context.pipelineRun.name)"
      - name: application-name
        value: site-gateway-os        # the source repository
      - name: workload-profile
        value: vm-instance
      - name: instance-name
        value: site-west              # workloads/site-west/
      - name: disk-digest
        value: "$(tasks.disk.results.disk-digest)"
```

`box1-vm-smoke` and `box1-bootc-apply` use `application-name` as both the Argo
Application and the VM, so an instance release passes the **instance** name there
(and `application-namespace: <instance>-dev`).

### Booted-digest check (`box1-bootc-status`, for #138)

`tasks/bootc-status.yaml` reads `bootc status --format json` in a running guest through
`virtctl ssh` and returns `booted-digest` and `booted-image`. It is read-only: the only
guest command is `sudo /usr/bin/bootc status --format json`, and it never upgrades,
switches, rolls back or reboots, so it cannot move an instance onto the shared channel
tag (unlike `box1-bootc-apply`). Optional `expected-digest` turns it into a gate.

The onboarding plugin's `vm-instance` verify runs it as `ci-vm-deploy` with the private
key Secret `box1-ci/vm-instance-deploy-ssh` (key `ssh-privatekey`, created outside Git;
**approval required, not created**). The instance bundle grants `ci-vm-deploy` `get` on
its VMI and `get`/`update` on `virtualmachineinstances/portforward` (the `legacy-erp`
`deploy-access.yaml` pattern). The source OS image must provide the guest user
`box1-deploy`, with the key's public half in its authorized keys and sudoers allowing
only `/usr/bin/bootc status --format json`; the #140 rule keeps `accessCredentials` for
`cloud-user` only, so the deploy key cannot be delivered by the guest agent.

### Channels

`vm-instance` workloads pin digests only (owner decision on #139). `box1-bootc-channel`
keeps moving the source image's shared `box1-ci/<source>:<channel>` tag, and no
per-instance tag exists. Requirement for #141: `box1-bootc-disk` records
`box1-ci/<source>:<channel>` as the installed system's update source, and the disk is
shared by every instance, so an in-guest `bootc upgrade` (or the automatic update
timer) would follow the shared tag rather than the instance's pinned digest. Instance
upgrades therefore need a digest-pinned switch in the guest (for example
`bootc switch …/box1-ci/<source>@sha256:<instance digest>`) and the automatic update
timer disabled in instance images.

## Code-only repository CI bundles (`ci/<repo>/`, `artifact` profile)

Owner decision on box1-docs#137: the Pipelines-as-Code Repository of a code-only
repository lives in `box1-workloads-dev/ci/<repo>/`, with an Application
`applications/<repo>-ci.yaml` that targets `box1-ci`. `box1-gitops-validate` renders
every `ci/*/kustomization.yaml` as well as `workloads/*/` (box1-docs#139). Contract:

- **Kinds:** only `Repository` (`pipelinesascode.tekton.dev/v1alpha1`),
  `ServiceAccount` (`v1`), `ImageStream` (`image.openshift.io/v1`), `Role` and
  `RoleBinding` (`rbac.authorization.k8s.io/v1`). Anything else fails, including
  Namespaces, Secrets (with or without data) and workloads.
- **Namespace:** every resource is in `box1-ci`.
- **Names:** exactly one Repository, named `<repo>`; at most one ImageStream, named
  `<repo>-bundle`; every ServiceAccount, Role and RoleBinding is named `<repo>-<purpose>`
  (suggested: `<repo>-release`, `<repo>-bundle-push`, `<repo>-release-observer`).
- **Repository:** `spec` sets only `url`, `concurrency_limit` and `settings`, and
  `settings` sets only `pipelinerun_provenance` and `github_app_token_scope_repos`
  (no `params`, `git_provider` or `policy`, which could reference Secrets or other
  hosts). `spec.url: https://github.com/box1-org/<repo>`,
  `settings.pipelinerun_provenance: default_branch`, and
  `github_app_token_scope_repos` lists only `box1-org/<name>` consumer repositories,
  never `box1-org/box1-gitops` or `box1-org/box1-workloads-dev`.
- **Roles:** every rule names its resources (`resourceNames`), uses no `*` anywhere
  (including `*/status`), never covers `secrets`, and never covers the `exec`,
  `attach`, `portforward`, `proxy` or `token` subresources. Verbs are `get`, `list` or `watch`, except a rule on exactly
  `imagestreams/layers` of exactly `<repo>-bundle`, which may also `update` (the
  registry push).
- **RoleBindings:** `roleRef` is a `Role` declared in the same bundle; subjects are
  ServiceAccounts in `box1-ci` declared in the bundle, or `ci-observe`.
- `ci/<repo>` must not share a name with a `workloads/<repo>` directory.

Cluster RBAC, or RBAC outside `box1-ci` (for example an Argo Application observer in
`openshift-gitops`), cannot live in `ci/<repo>/`; it belongs in `box1-gitops`. The
validator does not check `applications/*.yaml`.

### Bundle build and consumer PR (`artifact` profile, box1-docs#137)

The `quarkus-monorepo` template (box1-templates) generates `ci/<repo>/` with exactly:
the Repository `<repo>` (token scope: the one consumer repository), the ServiceAccount
`<repo>-release`, the ImageStream `<repo>-bundle`, and the Role and RoleBinding
`<repo>-bundle-push` (`get` and `update` on `imagestreams/layers` of `<repo>-bundle`,
bound to `<repo>-release`). There is no observer Role: nothing in the release observes a
workload. Two central Tasks run the release:

| Task | Runs as | Does |
| --- | --- | --- |
| `box1-maven-bundle` (`tasks/maven-bundle.yaml`) | `ci-test` on PRs (`push-image: 'false'`), `<repo>-release` on `main` | Fetches the revision, runs the multi-module `mvn verify -DskipITs=false` on the builder image, then copies each `<module>/target/quarkus-app/` of the root POM's `<modules>` to `/<module>/quarkus-app/`, writes `/SHA256SUMS`, and builds a deterministic one-layer `FROM scratch` OCI layout (fixed timestamps and owners, sorted entries, symlinks refused; the layout code follows `box1-ops-erp-simulator/scripts/make-oci-layout.py`). On `main` it pushes unprivileged with `skopeo copy --preserve-digests --digestfile` to `registry.apps.ocp.box1.org/box1-ci/<image-name>:<revision>` and fails unless the pushed digest equals the built layout's. Result `image-digest` (`not-published` on PRs). |
| `box1-bundle-consumer-pr` (`tasks/bundle-consumer-pr.yaml`) | `<repo>-release`, after `box1-security-gates` in `gate` mode | Refuses any `gate-policy` other than `pass`. If the source `main` moved past `revision`, does nothing (`superseded`). Otherwise rewrites the digest on the single `COPY --from=…/box1-ci/<repo>-bundle@sha256:<digest>` line of `consumer-path` in `box1-org/<consumer-repository>` and opens one PR from branch `bundle/<repo>`, or updates the open one (the PR body carries a `box1-bundle-source` marker; a PR without it is never touched). Zero or several such lines, a tag instead of a digest, or any other reference to the bundle (a `FROM … AS` alias, a `--mount … from=`) fail with the line numbers. The branch `bundle/<repo>` is owned by the automation: each release rebuilds it on the default branch and discards commits pushed to it by hand; a leftover branch whose tip is not a bump commit is refused. Already pinned: closes an obsolete bump PR, outcome `current`. Same proposal already open: `unchanged`, no write. Never merges. Results `pr-url`, `outcome`. |

Pipelines-as-Code scopes a release token to `github_app_token_scope_repos` only when each
listed repository is itself registered as a Repository in `box1-ci` (see
`AUTOMATION.md`). The consumer (for `site-gateway`, `site-gateway-os`, onboarded from
`rhel-image-vm`) must therefore be onboarded before the first PaC release of the bundle
repository; the onboarding build itself uses a Hub-minted token and does not depend on it.
The `push` step keeps its HOME, registry and auth configuration in its private `/tmp`,
not in the volumes the `mvn` step (repository code) can write.

`box1-quarkus-maven` is unchanged for services: it reads `target/jib-image.digest` at the
repository root, which a multi-module build does not produce. The Hub's
`developer-hub-onboarding-build` Role gains `get` on `imagestreams` in `box1-ci`, which
the onboarding plugin's `artifact` verify uses to confirm the published digest.

Contract tests (no cluster, GitHub or registry access; Python 3.9 and 3.11):

```sh
python3 platform/pipelines/tasks/test-maven-bundle.py
```

## Contract tests

```sh
BOX1_WORKLOADS_DEV=/path/to/box1-workloads-dev python3 platform/pipelines/tasks/test-gitops-validate.py
python3 platform/pipelines/tasks/test-gitops-promote.py
```

They need `kubectl` (or `oc`) for `kustomize`, and run on Python 3.9 and 3.11.
`ServiceProfileRegression` (only with `BOX1_WORKLOADS_DEV`) checks that every live
workload validates under the profile its Namespace declares, and that every `ci/`
bundle validates. The suites are not run by any pipeline yet; they are run by hand
before changing either Task. Wiring them into a `box1-gitops` PR pipeline is a
follow-up: the only existing PR pipeline (`.tekton/onboarding-plugin-guard.yaml`)
deliberately runs its guard from `main` and holds a GitHub token, so running PR-supplied
test code there would need a separate token-free step and a trust decision.
