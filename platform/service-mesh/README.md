# Box1 service mesh (`operate` profile)

Istio **ambient** mode (OpenShift Service Mesh 3) and Kiali, from
[box1-docs#23](https://github.com/box1-org/box1-docs/issues/23). There are no sidecars and no canary releases.
Run state and decisions:
[agent-runs/23-ambient-mesh](https://github.com/box1-org/box1-docs/tree/agent-run/23-ambient-mesh/agent-runs/23-ambient-mesh).

| Application (sync wave) | Path | Creates |
|---|---|---|
| `service-mesh-network` (0) | `network/` | Sets OVN local gateway mode (`routingViaHost: true`) on `networks.operator.openshift.io/cluster` by server-side apply. Ambient probes need it. |
| `service-mesh-operators` (0) | `operators/` | OSSM 3 operator (`stable-3.5`) and the Kiali operator (`stable`), each in its own namespace, with manual InstallPlan approval |

All Applications are manual-sync, like the other platform Applications.

**Coexistence:** the ingress operator already runs `istiod-openshift-gateway`
(revision `openshift-gateway`) in `openshift-ingress` for the Gateway API, and
owns the `*.istio.io` CRDs. Inspect the OSSM InstallPlan's CRD steps before
approving it. After install, `istiod-openshift-gateway` must stay healthy and the
GatewayClasses must stay Accepted.
