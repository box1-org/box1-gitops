# Box1 service mesh (`operate` profile)

Istio **ambient** mode (OpenShift Service Mesh 3) and Kiali, from
[box1-docs#23](https://github.com/box1-org/box1-docs/issues/23). There are no sidecars and no canary releases.
Run state and decisions:
[agent-runs/23-ambient-mesh](https://github.com/box1-org/box1-docs/tree/agent-run/23-ambient-mesh/agent-runs/23-ambient-mesh).

| Application (sync wave) | Path | Creates |
|---|---|---|
| `service-mesh-network` (0) | `network/` | Sets OVN local gateway mode (`routingViaHost: true`) on `networks.operator.openshift.io/cluster` by server-side apply. Ambient probes need it. |
| `service-mesh-operators` (0) | `operators/` | OSSM 3 operator (`stable-3.5`) and the Kiali operator (`stable`), each in its own namespace, with manual InstallPlan approval |
| `service-mesh-control-plane` (1) | `mesh/` | Namespaces `istio-system`, `istio-cni`, `ztunnel`; `Istio` `default` (ambient, `v1.31.1`, discovery selector `istio-discovery: enabled`, `box1-otel` tracing provider); `IstioCNI` and `ZTunnel` (privileged node DaemonSets); Prometheus `Telemetry`; istiod ServiceMonitor and ztunnel PodMonitor for user-workload monitoring; Argo CD RBAC for these kinds |
| `service-mesh-kiali` (2) | `kiali/` | `Kiali` in `istio-system`: OpenShift login, no cluster-wide access (an explicit list: `istio-system`, `ztunnel` and the seven Box1 service namespaces), metrics from Thanos Querier, traces from the Tempo gateway (tenant `dev`); its service account is bound to `cluster-monitoring-view` and `box1-traces-read-dev` |

All Applications are manual-sync, like the other platform Applications.

**Coexistence:** the ingress operator already runs `istiod-openshift-gateway`
(revision `openshift-gateway`) in `openshift-ingress` for the Gateway API, and
owns the `*.istio.io` CRDs. Inspect the OSSM InstallPlan's CRD steps before
approving it. After install, `istiod-openshift-gateway` must stay healthy and the
GatewayClasses must stay Accepted.

**Enrollment:** a namespace joins the mesh only when it carries both
`istio-discovery: enabled` (seen by this control plane) and
`istio.io/dataplane-mode: ambient` (ztunnel captures its traffic). Those labels
live on the Namespace manifests in `box1-workloads-dev`. Removing them is the
rollback.
