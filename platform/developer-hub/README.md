# Box1 Developer Hub

This directory is the **instance** Kustomize target for the `developer-hub` child
Application. `operator/` is a separate target for `developer-hub-operator`.
Neither child has automated sync. The existing root Application reads
`applications/`, registering both children after these files are published there.
There is deliberately no recursive directory source or shared Kustomization that
installs the Operator and the Backstage resource together.

## Compatibility checked on 2026-10-24

Read-only checks against `api.ocp.box1.org` found:

| Item | Observed value / chosen configuration |
| --- | --- |
| OpenShift release | `5.0.0-rc.7` |
| Operator catalog | `redhat-operators-v422`, namespace `openshift-marketplace` |
| Developer Hub package | `rhdh` |
| Release channel | `fast-1.9`, head `rhdh-operator.v1.9.7` |
| Advertised Backstage APIs | `rhdh.redhat.com/v1alpha3`, `v1alpha4`, `v1alpha5` |
| Supported install mode in that CSV | `AllNamespaces` only |
| Installed RHDH subscription / Backstage CRD | Neither present |
| Default StorageClass | `lvms-vg1`, `topolvm.io`, `WaitForFirstConsumer` |
| Cluster ingress domain | `apps.ocp.box1.org` |
| Argo CD applications | None present in `openshift-gitops` |

Current Red Hat 1.10 documentation was reviewed, but this cluster's available
package advertises 1.9.7, not a `fast-1.10` channel. This configuration therefore
uses the versioned 1.9 channel and 1.9-compatible API. Do not infer an Operator
channel from OpenShift's release number or assume that `fast` stays on 1.9.
`startingCSV` chooses the initial CSV, not a permanent version pin; later updates
within `fast-1.9` require OLM InstallPlan approval.

Catalog availability and API schema checks do **not** establish Red Hat support
for OpenShift 5.0 RC7 with a 4.22 catalog snapshot. Runtime compatibility remains
to be verified when installation is authorized. Recheck the catalog before a
future rollout; do not create a second Subscription if someone installs RHDH
outside this repository in the meantime.

## Instance configuration

- One Developer Hub replica, using `spec.deployment.patch.spec.replicas` in
  `v1alpha5`. The older `spec.application.replicas` field is absent in this API.
- Operator-managed local PostgreSQL, appropriate for this lab setup. Its default
  1 GiB ReadWriteOnce claim omits `storageClassName`, inheriting the verified
  default `lvms-vg1`. There is no `spec.database.storageClassName` field. Recheck
  the default before first sync; a changed default changes the selected class.
  Local LVM volumes are node-bound; this is not an HA database. Back up the
  database and use an external PostgreSQL service for a production deployment.
- Operator-managed Route at `https://developer-hub.apps.ocp.box1.org`, with the
  default edge TLS / HTTP redirect and cluster ingress certificate. A matching
  wildcard ingress certificate is required. No certificate private key is in Git.
- GitHub App integration, organization users/groups, and repository discovery
  limited to `box1-org`. Discovery reads `/catalog-info.yaml` on `main`; change
  `filters.branch` if a repository uses another branch. It does not create
  catalog files or publish repositories.
- GitHub sign-in requires a matching imported catalog User. Guest sign-in and
  bypassing catalog identity resolution are not enabled. An initial sign-in can
  fail until the organization provider completes its first successful import.

## External secret contract

Provision these Opaque Secrets in `rhdh` from a secret manager or private files
**before** syncing the instance. There are no plaintext Secret manifests, fake
credentials, ExternalSecret resources, or assumed secret-manager installations.

| Secret | Required keys |
| --- | --- |
| `developer-hub-secrets` | `BACKEND_SECRET`, `AUTH_SESSION_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`, `GITHUB_APP_PRIVATE_KEY` |
| `developer-hub-db` | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRESQL_ADMIN_PASSWORD` |

Use independent, randomly generated values for backend, session, and database
secrets. When `POSTGRES_USER=postgres`, set `POSTGRES_PASSWORD` and
`POSTGRESQL_ADMIN_PASSWORD` to the **same** generated database password: the
PostgreSQL image initializes the postgres role with its admin password, while
Backstage connects with `POSTGRES_PASSWORD`. Different values cause application
startup to fail with password authentication errors.
`BACKEND_SECRET` replaces the Operator default legacy backend token.
`GITHUB_APP_PRIVATE_KEY` must be the complete multiline PEM private key, not a
base64 representation of the PEM text. `POSTGRES_HOST` must be
`backstage-psql-developer-hub`, `POSTGRES_PORT` must be `5432`, and
`POSTGRES_USER` can be `postgres`. Keep database credentials stable across Pod
recreation; changing a Secret alone does not rotate an initialized database's
password. The Operator can generate database credentials when the named Secret
is missing; preprovision it to keep credential ownership external.

Register/install a GitHub App under **box1-org**. Set its homepage to
`https://developer-hub.apps.ocp.box1.org` and authorization callback to
`https://developer-hub.apps.ocp.box1.org/api/auth/github/handler/frame`.
Disable webhooks for this configuration. Grant organization Members read access and repository Metadata read access.
The Quarkus golden path additionally requires Administration, Contents, and
Pull requests write access. Install it on all organization repositories so newly
generated services are accessible immediately. Both the authentication provider and integration use the same App's client
credentials. Organization users must be discoverable by that App.

Example commands for a **later, authorized rollout**, with actual values kept
outside the repository (the env file excludes the separately supplied PEM key):

```sh
oc apply -f platform/developer-hub/namespace.yaml
oc -n rhdh create secret generic developer-hub-secrets \
  --from-env-file=/secure/path/developer-hub.env \
  --from-file=GITHUB_APP_PRIVATE_KEY=/secure/path/github-app.pem
oc -n rhdh create secret generic developer-hub-db \
  --from-env-file=/secure/path/developer-hub-db.env
```

If a secret manager already owns these Secrets, use its provisioning workflow
instead. Restart the Developer Hub deployment after updating environment-backed
Secrets so the application reads the new values.

## Staged rollout, only when authorized

1. Review/publish the changes and register the root/children through the existing
   GitOps process. Ensure Argo CD can read this repository. The namespace labels
   delegate namespaced management to `openshift-gitops`; the controller also
   needs Namespace and OLM resource permissions. Existing controller cluster
   rules allowed Namespace and OLM management at inspection time. Recheck policy
   if installation encounters `Forbidden`; do not grant blanket cluster-admin.
2. Manually sync **developer-hub-operator**. Review its generated InstallPlan
   before approving it. Wait for the installed CSV to reach `Succeeded` and the
   Backstage CRD to be established. An Argo Application becoming Synced does not
   prove that OLM finished installing its CRDs.
3. Confirm the installed CRD actually serves `v1alpha5`, then provision the
   instance namespace and external Secrets described above. Validate the instance
   against the installed schema before syncing it.
4. Manually sync **developer-hub**. Wait for PostgreSQL, the Developer Hub
   deployment, PVC binding, Route admission, plugin loading, and GitHub catalog
   imports. Verify HTTPS and sign-in with a `box1-org` member.

Read-only checks and a server dry run for those stages:

```sh
oc -n openshift-marketplace get packagemanifest rhdh -o yaml
oc -n rhdh-operator get subscription rhdh
oc -n rhdh-operator get installplan,csv
oc wait --for=condition=Established crd/backstages.rhdh.redhat.com --timeout=120s
oc get crd backstages.rhdh.redhat.com \
  -o jsonpath='{range .spec.versions[*]}{.name}{" served="}{.served}{"\n"}{end}'
oc get storageclass
oc apply --dry-run=server -k platform/developer-hub
oc -n rhdh get backstage,pods,pvc,route
oc -n rhdh logs deployment/backstage-developer-hub -c backstage-backend
```

The two manual sync boundaries are intentional. Sync waves on child Application
objects alone do not provide a dependable OLM/CRD readiness barrier. Do not add
`SkipDryRunOnMissingResource` to conceal a missing Backstage API.
Pruning is not automatic; do not delete the namespace or database PVC as part of
a routine upgrade.

## Install plugins through Extensions (lab environment)

This setup follows Red Hat's [Extensions installation procedure](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html/installing_and_viewing_plugins_in_red_hat_developer_hub/extensions-in-rhdh_plugins-in-rhdh#configure-rhdh-to-install-plugins-by-using-extensions_extensions-in-rhdh).
The feature is Technology Preview and plugin installation through the UI requires
`NODE_ENV=development`. GitHub authentication remains explicitly configured with
`auth.environment=production`; guest access is not enabled.

`dynamic-plugins-root` is a dedicated 5 GiB ReadWriteOnce PVC on `lvms-vg1`.
The Backstage deployment patch clears the default ephemeral volume source and
mounts this claim in both the installer and application containers. The claim is
in the same sync wave as Backstage because `WaitForFirstConsumer` needs the Pod
to schedule before binding the volume. It is excluded from Argo CD pruning.
The Deployment uses `Recreate` so only one Pod writes this shared cache; restarts
and upgrades cause a short outage. The PostgreSQL PVC is independent.

The installer copies `developer-hub-extensions-seed` into the PVC **only if**
`dynamic-plugins.extensions.yaml` is absent. This automates the documentation's
manual `oc cp` bootstrap before the installer loads the file, including on a
fresh installation. The seed enables GitHub discovery and the Extensions UI and
backend; existing frontend wiring is inherited from the bundled defaults.
The backend writes future UI changes to
`/opt/app-root/src/dynamic-plugins-root/dynamic-plugins.extensions.yaml`; the
installer sees that same file at `/dynamic-plugins-root/dynamic-plugins.extensions.yaml`.

The 1.9.7 installer rejects duplicate plugin entries between included files,
including overrides of plugins already present in its defaults. The startup
adapter therefore stages the writable file's plugin entries as the main plugin
list and includes the defaults once. It runs the image's installer from its
original working directory so npm retains bundled dependencies. Only the
input-config assignment is redirected in memory to the staged file; the image
is unchanged. The adapter fails clearly if that assignment changes in a future
image, so revalidate it with Operator upgrades. This preserves default frontend
wiring and supports enabling/disabling bundled plugins.

Git manages the bootstrap, environment, base app configuration, and storage.
After bootstrap, the PVC file owns UI-managed plugin choices. Editing the seed
ConfigMap does **not** overwrite an existing file or apply new plugin choices.
Back up this file with the PVC and avoid putting plaintext credentials in plugin
configuration. Continue to use environment variables backed by Secrets.
The main `dynamic-plugins.yaml` requires the GitHub scaffolder backend for the
Quarkus golden path. Other plugin choices come from the UI file; the installer
merges entries by package name and gives platform requirements precedence. Enabling/disabling discovery plugins through the UI can affect
GitHub catalog imports and sign-in identity provisioning.

To use it:

1. Sign in with GitHub and open **Administration > Extensions**.
2. Select a plugin and choose **Install**, or use its Actions to configure or
   enable/disable it. Save the configuration.
3. Restart the application with
   `oc -n rhdh rollout restart deployment/backstage-developer-hub`.
4. Wait for readiness and verify the plugin on the Installed tab. Plugin changes
   are loaded at startup; saving in the UI does not hot-reload the backend.

RBAC is currently disabled. If RBAC is enabled later, grant the appropriate
administrators the Extensions **Create** and **Read** permissions as described in
section 6.5.1 of the linked procedure.

## Manifest validation

The GitHub catalog plugin package in the 1.9.7 image is
`./dynamic-plugins/dist/backstage-plugin-catalog-backend-module-github-dynamic`.
Omitting `-dynamic` causes the plugin init container to fail with `npm pack`
ENOENT because that alternate directory does not exist. The installer logs list
the correct package among the default disabled plugins. After publishing a
correction, sync the ConfigMap through the `developer-hub` Argo CD application
and verify that its replacement Pod completes `install-dynamic-plugins`.

The GitHub discovery provider key is `providerId` to match the bundled plugin's
default configuration. A different key adds another provider rather than
replacing the default `${GITHUB_ORG}` placeholder, which can prevent the catalog
plugin from starting when that variable is unset.

Both targets can be rendered independently without a cluster:

```sh
kubectl kustomize platform/developer-hub/operator
kubectl kustomize platform/developer-hub
git diff --check
```

The Backstage spec was validated locally against the upstream Operator's
`release-1.9` v1alpha5 CRD schema, rejecting unknown fields. The schema is a
validation reference, not a CRD to install from this repository. OLM owns the
installed CRD. Embedded app and plugin configuration was also parsed as YAML.
Server-side Backstage validation and runtime checks must wait for Operator
installation; a dry run cannot validate an API that is absent.

The Application, Subscription, and OperatorGroup specs also passed the installed
cluster CRD schemas. A strict server-side dry run passed for both Namespace
objects, both ConfigMaps, the OperatorGroup, Subscription, and both Applications.
For that check only, namespaced objects were copied into the existing
`openshift-gitops` namespace in a temporary validation file, because dry-running a
Namespace creation does not make it available for subsequent requests. Target
namespace admission and controller permissions must still be checked at rollout.
No resources were persisted, and no InstallPlan was approved.

Primary references:

- [Red Hat Developer Hub 1.10 installation](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.10/html-single/installing_red_hat_developer_hub_on_openshift_container_platform/index)
- [Red Hat Developer Hub 1.9 configuration](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html-single/configuring_red_hat_developer_hub/index)
- [Red Hat Developer Hub 1.9 GitHub integration](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html-single/integrating_red_hat_developer_hub_with_your_git_provider/index)
- [Red Hat Developer Hub 1.9 authentication](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html-single/authentication_in_red_hat_developer_hub/index)
- [Red Hat Developer Hub backend secret](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html-single/customizing_red_hat_developer_hub/index)
- [Operator 1.9 CRD schema](https://github.com/redhat-developer/rhdh-operator/blob/release-1.9/config/crd/bases/rhdh.redhat.com_backstages.yaml)
- [Operator default PostgreSQL StatefulSet](https://github.com/redhat-developer/rhdh-operator/blob/release-1.9/config/profile/rhdh/default-config/db-statefulset.yaml)
- [Operator default Route](https://github.com/redhat-developer/rhdh-operator/blob/release-1.9/config/profile/rhdh/default-config/route.yaml)

## Quarkus Software Template

Phase 4 registers `box1-org/box1-templates/catalog-info.yaml` and its
`quarkus-rest-service` template. Open **Create → Create Quarkus Service**.
The required GitHub scaffolder backend module is managed in
`dynamic-plugins.yaml`; the installer deduplicates platform and UI entries by
package, with platform settings taking precedence. The Developer Hub App now
has Administration, Contents, and Pull requests write permissions and an
all-repositories installation. See [the golden-path guide](../pipelines/GOLDEN-PATH.md).

## Live platform connections

The Hub connects to `https://api.ocp.box1.org:6443` as cluster `box1` using
`rhdh/developer-hub-reader`. The token controller populates the Git-managed
`developer-hub-kubernetes-token` Secret; its `token` is injected through the
Deployment patch, and `ca.crt` is mounted for strict API TLS validation.
The read-only ClusterRole covers application resources, Routes, Pod logs and
Tekton v1 objects. It cannot read Secrets, execute in Pods, or mutate workloads.
Reads span namespaces because workloads and CI runs live in different namespaces.
ConfigMaps and Pod logs are readable; do not store credentials in either.

The existing OpenShift GitOps instance has a dedicated `developer-hub` apiKey
account with only `applications,get,default/*`. It has no login, sync, create,
delete, or administrative permissions. The separate manual-sync
`developer-hub-gitops-access` Application manages integration fields on its
Operator-owned ArgoCD CR while preserving the existing administrator groups.
No second Argo CD instance or administrator runtime credential is created.

Bootstrap order (also suitable for credential repair):

```sh
kubectl apply -f platform/developer-hub/kubernetes-access.yaml
kubectl apply -k platform/gitops/developer-hub-access
python3 platform/developer-hub/scripts/provision-connections.py
# Publish/reconcile GitOps, then sync the manual developer-hub application.
kubectl apply -k platform/developer-hub
kubectl -n rhdh rollout status deployment/backstage-developer-hub
kubectl -n rhdh exec -i deploy/backstage-developer-hub -c backstage-backend -- node \
  < platform/developer-hub/scripts/verify-connections.cjs
```

The bootstrap script uses existing administrative access to mint the dedicated
Argo token and writes it directly to `developer-hub-platform-secrets`; it prints
no credentials. The token expires in 90 days. Before expiry run with
`--rotate-argocd`, restart Hub, verify, and revoke the previous token by ID from
the Argo account. The Secret annotation records the new ID and creation time.
The service-account token is controller-managed and long lived; rotate by
recreating its Secret, waiting for population, and restarting Hub. Run the
provisioner after ingress CA rotation to refresh the mounted trust ConfigMap,
then restart Hub. TLS verification stays enabled; `NODE_EXTRA_CA_CERTS` adds the
cluster ingress CA for the Argo HTTPS route. Secret values and CA material are
provisioned from the live cluster and never committed to Git.

Platform plugin requirements are pinned in `dynamic-plugins.yaml` and override
incomplete UI connection placeholders for the same packages at installation.
The existing OCI Argo CD 1.0.2 backend and 2.4.3 frontend are retained.

All components use `backstage.io/kubernetes-id=<entity-name>` on workloads,
Pod templates, PipelineRuns and Argo CD Applications. Catalog annotations use
that ID, `janus-idp.io/tekton`, `argocd/instance-name=openshift-gitops`, and
`argocd/app-selector=backstage.io/kubernetes-id=<entity-name>`. There is no
namespace annotation, so the Hub can resolve CI runs in `box1-ci` as well as
Pods in the application namespace. Tekton propagates PipelineRun labels to
new TaskRuns/Pods. Existing retained CI runs are labeled once during rollout.
The template generates these same labels and annotations for future services.

The verification script uses the existing backend automation credential to
query the actual catalog, Kubernetes and Argo CD backend endpoints. It fails
on absent entities, missing workloads/Pods/Routes/CI runs, backend errors, or
missing selector-matched Applications; it needs no browser session.

References: [Red Hat 1.9 plugin configuration](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html-single/configuring_dynamic_plugins/index)
and [Backstage Kubernetes configuration](https://backstage.io/docs/features/kubernetes/configuration/).


## Provided APIs and endpoint testers

The Quarkus template emits a Component and an OpenAPI API entity in the same
`catalog-info.yaml`. `spec.providesApis` populates the service's **Provides APIs**
card. API **Definition** uses Developer Hub's built-in Swagger renderer and
**Try it out**; service Overview links also open the deployed `/q/swagger-ui/`.
The API definition is read from that service's live `/q/openapi` endpoint, keeping
it aligned with the deployed release. A new API entity needs the first service
deployment before its definition can be ingested. The Component can register
before deployment. Only `/q/openapi` reads under `*.apps.ocp.box1.org` are allowed
by the Hub URL reader.

Production OpenAPI documents name the public HTTPS Route as their server;
`PUBLIC_API_URL` can override it. Services allow CORS from the exact Hub origin,
with credentials disabled. Authentication added to a service must be represented
in its contract and supplied through Swagger **Authorize**.

Validate the catalog relationship, rendered contract, Swagger page, allowed
Hub-origin request, and rejected untrusted origin without a browser:

```sh
kubectl -n rhdh exec -i deploy/backstage-developer-hub -c backstage-backend -- node \
  < platform/developer-hub/scripts/verify-service-apis.cjs
```

References: [Red Hat API contracts and interactive testing](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html-single/navigate_red_hat_developer_hub_on_your_first_day/index)
and [Quarkus OpenAPI and Swagger UI](https://quarkus.io/version/3.40/guides/openapi-swaggerui/).

## Workload topology

The platform requires the bundled Topology plugin (2.9.4 in the 1.9.7 image).
Its Git-managed entry overrides the disabled Extensions choice and inherits the
image's `entity.page.topology/cards` mount point. Open a service's **Topology**
tab to view workloads and Pods. The existing Kubernetes connection, entity-ID
labels, Routes/Tekton custom resource configuration and reader permissions are
reused; no broader credentials are needed.

The **CD** tab continues to show Argo CD application details. Argo CD's own UI
provides its complete application resource tree; Topology is the Hub's workload
visualization. A browser-blocked Segment analytics request is independent of
both data connections.

## Zero-touch development onboarding

The Quarkus 1.1.0 template uses the `box1-scaffolder-onboarding-dynamic` module.
Canonical source and tests are in `box1-templates/plugins/box1-onboarding`;
`onboarding/plugin/` is generated transport for the runtime ConfigMap. The init
adapter copies ConfigMap data into a writable emptyDir before npm packaging,
and invalidates this local module's cache hash on every boot to avoid the 1.9
installer deleting its reinstalled directory during stale-hash cleanup.

The Pod uses an automatically rotated projected token for the dedicated
`developer-hub-onboarding` ServiceAccount, with permissions for durable
state/leases, initial build Secrets/PipelineRuns, and readiness GET requests.
It cannot mutate workload Deployments, Argo Applications, Namespaces or RBAC.
The Kubernetes and Argo CD plugin connections continue using their separate
read-only credentials. Application resources are reconciled by Argo only after
validated, development-only PR merges.

Inspect provisioning state and task logs if onboarding fails:

```sh
kubectl -n rhdh get configmap box1-onboard-SERVICE -o jsonpath='{.data.status\.json}'
kubectl -n rhdh get lease box1-onboard-SERVICE
kubectl -n box1-ci get pipelinerun -l backstage.io/kubernetes-id=SERVICE
```

Retry the template with the same request parameters to resume its repository,
PR and build checkpoints. Active tasks hold renewable service-specific leases.
Completed first builds are reused; failed first builds allow at most three
recorded attempts across resumptions. Build tokens are one-hour, source-only
Contents-read GitHub installation tokens stored only in Kubernetes Secrets.
The workflow deletes the Secret on successful build; a PipelineRun owner
reference also enables normal garbage collection. Other environments need a
separate approved workflow.

Provisioning is marked COMPLETE only after the verified deployment and
idempotent catalog registration both succeed. Catalog conflicts reuse the
matching entry; other registration errors fail the task and status record.
The final Hub API acceptance, partial-failure resume and completed replay for
shipping-service are recorded in `box1-templates/verification/shipping-service`.
