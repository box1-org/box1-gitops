# Box1 OpenShift AI lab

OpenShift AI 3.4.2 runs the dashboard, workbenches and KServe on Box1.
The test project contains a CPU Jupyter workbench, 10 GiB persistent volume,
dedicated NooBaa ObjectBucketClaim and an Iris classifier served by MLServer 1.7.1.
Tracking: https://github.com/box1-org/box1-docs/issues/2

## Compatibility and dependencies

This is an explicitly authorized **lab-only installation** on OpenShift
5.0.0-rc.7 / Kubernetes 1.36.5. Vendor support for this combination is **not
established**. Red Hat's current 3.x matrix lists OpenShift 4.19.9+, 4.20,
4.21 and 4.22 for AI 3.4; the installation chapter lists a narrower range.
Neither lists OpenShift 5.0. Do not treat successful tests as vendor support.
A supported deployment requires a separate supported OpenShift cluster or
written vendor confirmation. Do not attempt an in-place OpenShift downgrade.

- [Supported configuration matrix](https://access.redhat.com/articles/7137904)
- [Installation and component dependencies](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/installing_and_uninstalling_openshift_ai_self-managed/installing-and-deploying-openshift-ai_install)
- Existing cert-manager 1.20.1 is used by KServe. No Serverless/Service Mesh
  Operator is needed for this Standard/RawDeployment CPU example.
- Existing LVMS `lvms-vg1` supplies RWO storage; NooBaa supplies S3.
- The only RTX 5090 GPU remains allocated to the existing `vllm/vllm-test`.
- Pipelines, distributed training, NIM, model registry and other optional
  DataScienceCluster components are Removed. Operator-managed shared gateway,
  authentication, monitoring and model-controller resources are also installed.

## GitOps ownership and installation order

`applications/openshift-ai-operator.yaml`, `openshift-ai.yaml` and
`openshift-ai-test.yaml` are manual-sync Argo CD Applications discovered by
`box1-root`. OLM upgrades also require manual InstallPlan approval; the channel
is `stable-3.4`, starting CSV `rhods-operator.3.4.2`. Review future plans before
approval: startingCSV does not freeze the subscription permanently.

1. Sync `openshift-ai-operator`, review and approve the matching OLM InstallPlan,
   and wait for its CSV to reach Succeeded.
2. Sync `openshift-ai`; wait for `default-dsci` and `default-dsc` to report Ready.
3. On a fresh cluster, apply the `test/` namespace, quota, limits, access,
   ObjectBucketClaim and PVC first. Wait for the OBC to become Bound.
4. Run `python3 validation/provision-connection.py` from this directory while
   authenticated with kubectl. This creates `box1-ai-test/noobaa-connection`
   directly from the OBC credentials, using server-side apply and no credential
   output or last-applied annotation. Never export this Secret to Git.
5. Sync `openshift-ai-test`. The notebook requires that connection. The model
   initially waits for its S3 artifacts; execute the training cell below.

The workbench manifest preserves its authentication sidecar and TLS volumes.
Those referenced ConfigMaps, TLS Secret and workbench ServiceAccount are
created by the notebook controller. The main workbench image and MLServer
image are digest-pinned. The NooBaa bucket name in `test/iris.yaml` is the actual
OBC-assigned name from this lab; update `storageUri` after provisioning a new OBC
in another environment. It is an identifier, not a credential.

## Browser workflow and reproducible checks

Open https://rh-ai.apps.ocp.box1.org and sign in as `mike`. Open **Box1 AI test**.
The alias https://data-science-gateway.apps.ocp.box1.org also redirects there.
The project RoleBinding grants `mike` project admin; the dashboard's default
Auth resource allows authenticated OpenShift users, while project visibility
and operations remain subject to OpenShift RBAC.

Open **Workbenches → box1-workbench**. The first browser-created workbench used
Jupyter Data Science CPU Python 3.12, image selection 3.4 (d3137ca). Its resolved
image digest is recorded in `test/workbench.yaml`.

Open or upload `validation/box1-ai-smoke.ipynb` in JupyterLab. Its cells:

1. Write/read an S3 object with TLS verification, verify access to unrelated
   `first.bucket` returns 403, train LogisticRegression on sklearn's Iris data,
   predict class 0 for `[5.1,3.5,1.4,0.2]`, and upload the model and settings.
2. Verify saved files after **Stop → Stopped → Start → Ready** in the dashboard.
   Run this cell after a real workbench restart, before rerunning the first cell.
3. POST the same input to the internal KServe v2 inference endpoint and assert
   HTTP 200 and prediction `[0]`.

Notebook outputs contain the observed successful results. No credentials are
embedded. The model artifacts are trusted locally trained files; do not replace
them with untrusted serialized Python models.

The serving endpoint is cluster-internal HTTP:
`http://iris-predictor.box1-ai-test.svc.cluster.local:8080/v2/models/iris/infer`.
There is no public model Route or model authentication layer. This lab example
is reachable from cluster workloads with network connectivity. Add appropriate
network/access policy before serving sensitive models or data.

## Resources and verification

Observed 2026-10-25, America/New_York:

- Operator CSV Succeeded; DSCInitialization and DataScienceCluster Ready.
- Dashboard showed the project, workbench Ready and Iris deployment Ready.
- A real browser notebook executed; S3 round trip passed; unrelated bucket 403.
- Stop/Start recreated the workbench pod; notebook, 41-byte marker and 975-byte
  model remained accessible. Restarted pod UID:
  `0e6f546c-a2e8-463e-952a-1cf081af7e45`.
- MLServer downloaded the two model objects over verified TLS and returned
  HTTP 200 / class 0 to the notebook.
- Anonymous dashboard and notebook requests returned HTTP 302 to login; curl
  validated the public certificate without disabling certificate verification.
- All existing Argo CD Applications remained Synced/Healthy; cluster operators
  were Available=True, Degraded=False in the final check. Existing vLLM,
  Developer Hub, Keycloak, NooBaa and service deployments retained availability.

| Resource | Request | Limit | Observed idle sample |
| --- | --- | --- | --- |
| Workbench main container | 2 CPU / 4 GiB | 2 CPU / 4 GiB | Pod 16m CPU / 615 MiB |
| Workbench auth proxy | 100m / 64 MiB | 100m / 64 MiB | Included above |
| Model | 250m / 512 MiB | 1 CPU / 2 GiB | 2m CPU / 407 MiB |
| Storage initializer | 100m / 100 MiB | 1 CPU / 24 GiB | Short-lived; not sampled |

The initializer's operator-provided 24 GiB ceiling initially exceeded the
16 GiB project limit quota. Final quota is 32 GiB limits, 10 GiB requests,
4 CPU requests, 8 CPU limits, zero GPU, 30 GiB storage and 12 pods. The memory
ceiling is not a reservation; model requests remain small. Node samples changed
from 1136m CPU / 63810 MiB memory before installation to 3137m / 71566 MiB
after testing; these are single samples, not a controlled performance comparison.

## Recovery and cleanup

Routine workbench Stop/Start was tested. Full uninstall and disaster recovery
were **not tested**. LVMS and NooBaa classes use Delete reclaim policy: deleting
the PVC or OBC can destroy notebook or bucket data.

- To stop only the experiment, stop the workbench in the dashboard and set the
  InferenceService annotation `serving.kserve.io/stop: "true"` in Git, then sync.
  Keep the PVC/OBC and connection. Manual Argo sync prevents automatic restart
  while operating through the dashboard.
- Before any removal, back up the notebook volume and S3 objects to an independent
  destination and verify the backup. Merely retaining manifests is not a backup.
- Remove/disable the three child Applications in Git before uninstalling so
  `box1-root` cannot recreate them. These Applications deliberately have no
  resources finalizer and no automated pruning.
- Remove the test InferenceService and Notebook first, preserving PVC/OBC until
  their data is backed up and explicitly approved for removal. Follow Red Hat's
  version-specific uninstall procedure for DataScienceCluster, initialization,
  CSV and Subscription. Do not delete shared cert-manager, LVMS, NooBaa or GPU
  operators. Review operator-owned gateway/auth/monitoring cleanup carefully.
- To recover configuration, restore this Git revision and reconcile operator,
  components, connection and test resources in the order above; restore actual
  data from backup. Operator image/channel availability is a recovery prerequisite.

A lab run does not resolve the unsupported OpenShift version combination.
No production support, HA behavior, GPU integration, load testing or full
uninstall/reinstall recovery is claimed.
