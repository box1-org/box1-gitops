# Box1 observability (`operate` profile)

Distributed tracing and user-workload monitoring for Box1, from
[box1-docs#22](https://github.com/box1-org/box1-docs/issues/22). Nothing here
uses object storage. Centralized logging is deferred to
[box1-docs#82](https://github.com/box1-org/box1-docs/issues/82).

| Application (sync wave) | Path | Creates |
|---|---|---|
| `observability-operators` (0) | `operators/` | Red Hat build of Tempo, Red Hat build of OpenTelemetry and Cluster Observability Operator, `stable` channel, manual InstallPlan approval |
| `user-workload-monitoring` (0) | `user-workload-monitoring/` | `cluster-monitoring-config` with `enableUserWorkload: true` |
| `observability-tracing` (1) | `tracing/` | Namespace `box1-observability`, `TempoMonolithic` `box1` (10 Gi PV on the default class, 72 h retention, OpenShift-mode gateway with tenant `dev`, Jaeger UI through the gateway), `OpenTelemetryCollector` `box1`, per-tenant trace ClusterRoles, NetworkPolicies |
| `observability-dashboards` (2) | `dashboards/` | Perses datasource `box1-thanos-querier` (default) and dashboard `box1-order-flow`, shown under Observe → Dashboards |
| `observability-console` (2) | `console/` | `UIPlugin` `distributed-tracing` (console Observe → Traces) and Argo CD access to UIPlugins |

All five Applications are manual-sync, like the other platform Applications.

## Data path and access

Services export OTLP to `box1-collector.box1-observability.svc:4317` (gRPC)
or `:4318` (HTTP), unauthenticated. The collector batches, limits memory and
forwards to the Tempo gateway `tempo-box1-gateway:4317`. It uses TLS with the
service CA, its service-account token and the tenant header `X-Scope-OrgID: dev`.

The gateway runs in the Tempo pod. It authorizes each request with OpenShift
RBAC on resource `dev`, resourceName `traces`, in group `tempo.grafana.com`:

| Who | Access | Granted by |
|---|---|---|
| Collector (`box1-collector`) | write (`create`) | ClusterRole `box1-traces-write-dev`, bound |
| Cluster admins, and service accounts with wildcard `get` (for example Argo CD and some operators) | read (`get`) | built-in |
| Other users or groups | read (`get`) | bind ClusterRole `box1-traces-read-dev`; the user must also be able to view at least one namespace |

Write authorization covers only the collector-to-gateway hop. The collector
itself accepts unauthenticated OTLP from any namespace and writes everything
as tenant `dev`.

Two UIs share that access check:
- **Console:** Observe → Traces, from the COO `distributed-tracing` UIPlugin.
- **Jaeger UI:** its Route now targets the gateway, and the UI lives at
  `https://<route>/api/traces/v1/dev/search` (no longer `/`). It is deprecated
  upstream and kept alongside the console view for now.

Tempo's own API (3200) trusts any tenant header, so it is not reachable from
other pods. Tempo is not scraped by user-workload monitoring.

Switching to multitenancy hid traces written earlier in single-tenant mode;
they expire with the 72 h retention. Rolling back means reverting the Tempo,
collector and NetworkPolicy changes together, which hides traces written as
`dev` until they expire.

## Metrics, alerts and dashboards

- **Scraping:** user-workload monitoring scrapes the seven services through
  ServiceMonitors in `box1-workloads-dev` (`workloads/<service>/servicemonitor.yaml`).
  The adapter is scraped every 15 s; the others every 30 s.
- **Alerts:** PrometheusRules live next to the service that owns the metrics,
  because user-workload rules only see their own namespace.

  | Rule | Namespace | Alerts |
  |---|---|---|
  | `fulfillment-adapter-erp` | `fulfillment-adapter-dev` | `Box1ErpAcknowledgementDelayed`, `Box1ErpAwaitingOperator`, `Box1FulfillmentNeedsAttention`, `Box1FulfillmentFilesQuarantined`, `Box1FulfillmentMetricsStale`, `Box1ServiceDown` |
  | `order-service-flow` | `order-service-dev` | `Box1OrdersStuck`, `Box1OrderOutboxDelayed`, `Box1ServiceDown` |
  | `inventory-service-flow` | `inventory-service-dev` | `Box1InventoryDeadLetters`, `Box1ServiceDown` |
  | `<service>-availability` | notification, asset, scenario-controller, operations-console | `Box1ServiceDown` |

  Rules carry `openshift.io/prometheus-rule-evaluation-scope: leaf-prometheus`, so
  the user-workload Prometheus evaluates them (no Thanos Ruler lag). Alerts appear
  under Observe → Alerting and go to the platform Alertmanager.

  `Box1ErpAcknowledgementDelayed` counts from when the adapter accepts a request:
  it fires once the oldest unacknowledged request is over 30 s old for 15 s.
  Worst case is about 90 s, including the adapter's 15 s gauge refresh, a 15 s
  scrape and 15 s evaluation. Thresholds are lab starting points; measure and
  revise them.
- **Dashboard:** `box1-order-flow` (Perses, in `box1-observability`) shows:
  - order age and stuck orders, and order state transitions;
  - ERP acknowledgement age, backlog and operator queue;
  - adapter errors (ERP result outcomes, uploads, dead-lettered events, quarantined files);
  - pipeline health.

  Its default datasource is the cluster Thanos querier, so viewers need
  permission to query cluster metrics (for example `cluster-monitoring-view`).

## Resources managed outside this repository

**UIPlugin `monitoring` (with Perses).** OpenShift Virtualization's
`virt-platform-autopilot` (asset `monitoring-ui-plugin`, deployment
`openshift-cnv/virt-platform-autopilot`) created it at 2026-11-06 21:56Z. That
was about 20 s after the Cluster Observability Operator installed the UIPlugin
CRD. It is labelled `platform.kubevirt.io/managed-by: virt-platform-autopilot`
and the autopilot reconciles it continuously.

Its spec, recorded here for reference only:

```yaml
apiVersion: observability.openshift.io/v1alpha1
kind: UIPlugin
metadata:
  name: monitoring
spec:
  type: Monitoring
  monitoring:
    perses:
      enabled: true
```

It enables `monitoring-console-plugin` in the console and runs `perses` and
`perses-operator` in `openshift-cluster-observability-operator` (about 85 Mi
idle).

Argo CD deliberately does not manage it, so two controllers do not own one
object. Edits or deletes are reverted by the autopilot. A supported way to turn
it off through HyperConverged has not been established. Removing the COO (and
with it the UIPlugin CRD) makes the autopilot skip the asset.

## Install order

1. Sync `observability-operators`. Approve the InstallPlans after checking
   their CSV versions, then wait for the CSVs to report `Succeeded`.
2. Sync `user-workload-monitoring`. Wait for the Prometheus and Thanos Ruler
   pods in `openshift-user-workload-monitoring` to be ready.
3. Sync `observability-tracing`. Wait for the TempoMonolithic `Ready`
   condition, the `tempo-box1` PVC to bind, and the collector Deployment.
4. Sync `observability-console`, then check that Observe → Traces lists
   `box1-observability/box1` with tenant `dev`.
5. Turn on trace export in each service in `box1-workloads-dev`.

## Outage behaviour

Services export asynchronously, so a collector or Tempo outage drops spans
and does not affect requests. The collector keeps a bounded queue of 2000
export requests and retries for up to 120 s, then drops spans. Its
`otelcol_exporter_send_failed_spans` (no `_total` suffix in collector v0.158) metric counts the drops. User-workload
monitoring scrapes it through the ServiceMonitor that the operator creates.

## Disable and rollback

- **Disable tracing:** set each service's trace exporter back to `none` in
  `box1-workloads-dev`, then delete the `observability-tracing` Application
  with cascade. This deletes the Tempo PVC and the stored traces. No business
  data is stored here.
- **Disable user-workload monitoring:** delete the `user-workload-monitoring`
  Application, or set `enableUserWorkload: false`.
- **Remove the operators:** delete the CRs first. Then delete the
  Subscriptions and CSVs. The CRDs are left in place unless removed by hand.

## User-workload monitoring sizing

`user-workload-monitoring-config` is not managed yet. Prometheus therefore
uses OpenShift defaults: emptyDir storage and default retention, so metric
history is lost when the pod restarts. Retention and a PVC on `lvms-vg1`
will be set once usage is measured. That ConfigMap lives in a namespace
created only after UWM is enabled, so it is a follow-up change.

## Lab limits

These run on a single node with one replica each and no HA. Vendor support
for these operator versions on OpenShift 5.0.0-rc.7 is not established.
