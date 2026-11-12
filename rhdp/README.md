# Box1 RHDP installation

This chart is the Box1 entry point for the RHDP `ocp4_workload_field_content`
role (`agnosticd.core_workloads`). The role creates one Argo CD Application,
`field-content`, that renders this chart. The chart then creates one child
Application per enabled component.

The homelab deployment (`applications/*.yaml` → `platform/*` on `main`) is
not affected. RHDP children use the same `platform/` manifests and receive
cluster values through Argo CD `kustomize.patches`/`images`, rendered here.
Nothing in `platform/` is copied.

Tracking issue: box1-org/box1-docs#165. An example catalog is in
`examples/catalog-vars.yaml`.

## How values reach the cluster

- The role renders this chart from **inline values only**; it never reads a
  values file, so `values.yaml` holds the RHDP defaults. A catalog overrides
  them with `ocp4_workload_field_content_helm_values`.
- The role owns, and overwrites as whole keys, `deployer`, `gitops`,
  `litemaas` and `multi_user`. Box1 settings live under other keys.
- `templates/applications.yaml` builds each child Application. It adds:
  - Subscription patches: `redhat-operators`, Automatic approval, no
    `startingCSV`;
  - Route hosts, and PVC/OBC storage classes;
  - a `box1-platform-settings` ConfigMap (domain, issuer, git org,
    registry and other URLs) that Tasks and Jobs read;
  - image mappings for the homelab ART `cli` image and the `box1-cli` /
    `box1-python` Job placeholders;
  - any component-specific patches from `templates/_patches-*.tpl`.
- Every child has `retry` (unlimited, with backoff) and
  `SkipDryRunOnMissingResource`. Argo CD never retries a failed automated
  sync for the same revision, and operators, CRDs and inputs arrive late.
- Components that cannot run are **skipped, not failed**, and the reason is
  recorded in `box1-rhdp-system/box1-rhdp-plan`. Examples: object storage
  without `storage.objectStore: odf`, Lightspeed without LiteMaaS, Loki
  without `storage.rwoClass`.

## Profiles

A component is rendered when **any** of its profiles is on and its
`requires` hold. Set `components.<key>.enabled: false` to opt out.

| Profile | Components (Application names) | Needs |
| --- | --- | --- |
| `core` | (Kafka: `kafka-operator`, `box1-kafka`; disabled by default) | AMQ Streams serving `kafka.strimzi.io/v1` |
| `rhbk` | `keycloak-rhbk` | RHDP RHBK in `keycloak` |
| `developer` | `pipelines-operator`, `registry-default-route`, `pipelines-config`, `pipelines-ci`, `developer-hub-operator`, `developer-hub`, `dev-spaces-operator`, `dev-spaces`, `box1-sandboxes`, `reposilite`, `mailhog`, `box1-workloads-dev`, `box1-service-namespaces` | inputs Secret, demo git org, published builder image and onboarding plugin |
| `operate` | `service-mesh-operators`, `service-mesh-network`, `service-mesh-control-plane`, `service-mesh-kiali`, `observability-operators`, `user-workload-monitoring`, `observability-logging`, `observability-tracing`, `observability-console`, `observability-dashboards`, `box1-service-namespaces` | logging: `objectStore: odf` and `rwoClass` |
| `security` | `acs-operator`, `acs`, `rhtpa-operator`, `rhtpa-prerequisites`, `rhtpa` | RHTPA: `objectStore: odf` |
| `ai` | `lightspeed-operator`, `lightspeed`, `langfuse` | Lightspeed: LiteMaaS; Langfuse: `objectStore: odf` |

## Cluster prerequisites

- **OpenShift GitOps** with **cluster-admin** for the application controller:
  `ocp4_workload_openshift_gitops_setup_cluster_admin: true`.
  - Do not add an `argoproj.io/Application` health check. The root
    Application has no retry, so one slow child would stop the later waves.
- **RHBK** from `ocp4_workload_authentication_keycloak`: namespace `keycloak`,
  CR `keycloak`, Service `keycloak:8443`, host `sso.<domain>`.
  - Set `ocp4_workload_authentication_keycloak_default_realm: box1` so the
    lab users are in the realm Box1 uses.
- The **internal registry** must be `Managed`. Jobs use the
  `openshift/cli` imagestream, and builds push to it through the default route.
- A **default StorageClass**, or `storage.rwoClass`.
- For `objectStore: odf`: ODF Multicloud Object Gateway, with class
  `openshift-storage.noobaa.io`.

## External credentials: `box1-rhdp-system/box1-rhdp-inputs`

Credentials that cannot be generated are never passed as chart values; the
role prints values and stores them in the root Application. Create this
Secret once `box1-rhdp-system` exists; the chart creates it in its first
sync wave. The reconcilers pick it up within 10 minutes.

```bash
oc create secret generic box1-rhdp-inputs -n box1-rhdp-system \
  --from-file=PAC_GITHUB_APP_ID=pac-app-id \
  --from-file=PAC_GITHUB_APP_PRIVATE_KEY=pac-app.pem \
  --from-file=PAC_WEBHOOK_SECRET=pac-webhook-secret \
  --from-file=RHDH_GITHUB_APP_ID=rhdh-app-id \
  --from-file=RHDH_GITHUB_APP_CLIENT_ID=rhdh-client-id \
  --from-file=RHDH_GITHUB_APP_CLIENT_SECRET=rhdh-client-secret \
  --from-file=RHDH_GITHUB_APP_PRIVATE_KEY=rhdh-app.pem
```

| Key | Profile | Required |
| --- | --- | --- |
| `PAC_GITHUB_APP_ID`, `PAC_GITHUB_APP_PRIVATE_KEY`, `PAC_WEBHOOK_SECRET` | developer | yes. The GitHub App webhook URL must be this cluster's PaC route. |
| `RHDH_GITHUB_APP_ID`, `RHDH_GITHUB_APP_CLIENT_ID`, `RHDH_GITHUB_APP_CLIENT_SECRET`, `RHDH_GITHUB_APP_PRIVATE_KEY` | developer | yes. Callback: `https://developer-hub.<domain>/api/auth/github/handler/frame`. |
| `REDHAT_REGISTRY_DOCKERCONFIGJSON` | developer | no. Default: the `registry.redhat.io` entry of the cluster pull secret. |
| `ENTITLEMENT_CERT`, `ENTITLEMENT_KEY`, `LEGACY_ERP_SSH_KEY`, `VM_STATUS_SSH_KEY` | developer (`ci.optionalRepositories.bootc`) | only for bootc/ERP |
| `LITEMAAS_API_KEY` | ai, developer Lightspeed | no. It overrides the key the role passes. |

Credential reconcilers run as a Sync hook and then every 10 minutes
(CronJob `box1-credentials` in each consuming namespace). They pick up
inputs added later. They log key names only, write with Server-Side Apply,
and create generated values once without overwriting them.

| Secret | Namespace | Source |
| --- | --- | --- |
| `keycloak-client-secret-{developer-hub,langfuse,rhacs-oidc,rhtpa-ci}` | keycloak | the `keycloak-rhbk` reconcile Job (Keycloak-generated) |
| `pipelines-as-code-secret` | openshift-pipelines | inputs |
| `redhat-registry-pull`, `rhtpa-secret`, `rhacs-secret`, ConfigMap `rhacs-central-ca` | box1-ci | cluster pull secret or inputs; Keycloak; RHACS Central API |
| `developer-hub-secrets` (written only when complete), `developer-hub-lightspeed-secrets`, `developer-hub-lightspeed-litemaas`, `developer-hub-platform-secrets` (Argo CD token), ConfigMap `developer-hub-platform-trust` | rhdh | generated; inputs; Keycloak; Argo CD API; router and service-account CAs |
| `acs-oidc-config` | stackrox | Keycloak |
| `rhtpa-database`, `rhtpa-ci` | trusted-profile-analyzer | generated; Keycloak |
| `lightspeed-litemaas-credentials` | openshift-lightspeed | inputs or `box1-rhdp-litemaas` |

## Keycloak

`components/keycloak-rhbk` does not import a realm. The RHDP role already
imports its own realm (users and the OpenShift OAuth client), and a second
`KeycloakRealmImport` would collide with it; realm imports are also skipped
once a realm exists.

Instead, the `box1-realm-reconcile` Sync-hook Job uses kcadm on every sync.
It:

- creates the realm only if it is missing, and warns;
- applies the Box1 clients and roles with `partialImport`, skipping ones that
  already exist;
- adds client scope mappings and service-account grants;
- grants `rhtpa-admin` to `keycloak.adminUsers`;
- publishes the generated secrets of the confidential clients.

## Status and checks

- `oc get cm box1-rhdp-plan -n box1-rhdp-system -o yaml`: rendered and
  skipped components, warnings, settings.
- `oc get cm box1-rhdp-status -n box1-rhdp-system -o yaml`: the live
  preflight, refreshed every 5 minutes. It covers:
  - input keys;
  - operator channels in the catalog;
  - StorageClasses and the object store;
  - the registry;
  - Keycloak readiness;
  - controller cluster-admin;
  - the Kafka API.
- Credential progress: `oc logs -n <ns> job/<latest box1-credentials job>`
  (lines start with `WAITING:`).

## Local tests

```bash
rhdp/tests/render.sh              # helm lint + scenario matrix (needs helm, kubectl, Python + PyYAML)
rhdp/tests/homelab-regression.sh  # platform/ output vs origin/main for every homelab Application
python3 -m unittest discover -s platform/pipelines/tasks -p 'test-*.py'
```

`check.py` renders the chart for each scenario in `tests/scenarios.py`
(profiles, object store, git org, LiteMaaS, Pipelines reuse, multi-user). It
applies each Application's patches as Argo CD's `kustomize edit` would,
builds every source, and fails on any of:

- duplicate Applications or source paths;
- missing `retry` or required sync options;
- homelab-only values: `apps.ocp.box1.org`, `lvms-vg1`,
  `redhat-operators-v4*`, `/auth/realms`, the ART image, Manual
  InstallPlans, `box1-org` when another org is set, and NooBaa without
  `odf`;
- a leaked LiteMaaS key;
- malformed `printf` output.

## Not verified on a live cluster

The tests validate rendering only. These remain **not tested** until a
fresh RHDP deployment:

- **Operators:** every channel exists on the RHDP OpenShift version.
- **Server-Side Apply:** Argo CD SSA and ServerSideDiff on TektonConfig and
  the image registry Config.
- **Keycloak:** kcadm `partialImport` and the scope-mapping calls against
  RHBK 26.2.
- **Images:** the `openshift/cli` imagestream contents and pull access.
- **Registry route:** trust for buildah, skopeo and plugin pulls.
- **ACS:** the declarative OIDC provider format, and same-namespace
  SecuredCluster registration without a manual init bundle.
- **RHTPA:** S3 over the MCG public route; router-TLS ingress.
- **Developer Hub:** the Argo CD token mint on GitOps `latest`; the
  Kubernetes plugin over `kubernetes.default.svc`.
- **LiteMaaS:** with llama-stack (`remote::vllm`) and with OLS
  (`type: openai`, URL suffix).
- **Demo org:** the content of the forked `box1-workloads-dev` and
  `box1-templates` repositories (hostnames, image references, Namespace
  manifests that overlap `box1-service-namespaces`).
- **Builder and plugin:** publishing the builder image and the onboarding
  plugin outside the homelab registry.

## Removal

The role does not implement destroy. Deleting the `field-content`
Application removes its children, but no resources are pruned:
`prune: false`, and the namespaces carry `Prune=false,Delete=false`.
Secrets written by Jobs are not tracked by Argo CD. These changes stay in
place and must be reverted by hand:

- the ArgoCD CR account/policy lines added for Developer Hub;
- the merged `enableUserWorkload`;
- the registry default route.
