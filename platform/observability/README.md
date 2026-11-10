# Box1 observability (`operate` profile)

Distributed tracing and user-workload monitoring for Box1, from
[box1-docs#22](https://github.com/box1-org/box1-docs/issues/22), and
centralized logging from
[box1-docs#82](https://github.com/box1-org/box1-docs/issues/82). Only logging
uses object storage (a NooBaa bucket); tracing and metrics do not.

| Application (sync wave) | Path | Creates |
|---|---|---|
| `observability-operators` (0) | `operators/` | Red Hat build of Tempo, Red Hat build of OpenTelemetry and Cluster Observability Operator (`stable`), Loki Operator (`stable-6.7`) and Red Hat OpenShift Logging (`stable-6.7`), all with manual InstallPlan approval |
| `user-workload-monitoring` (0) | `user-workload-monitoring/` | `cluster-monitoring-config` with `enableUserWorkload: true` |
| `observability-tracing` (1) | `tracing/` | Namespace `box1-observability`, `TempoMonolithic` `box1` (10 Gi PV on the default class, 72 h retention, OpenShift-mode gateway with tenant `dev`, Jaeger UI through the gateway), `OpenTelemetryCollector` `box1` (traces; edge-site logs and metrics), per-tenant trace ClusterRoles, the collector's Loki application-write ClusterRole, NetworkPolicies |
| `observability-logging` (1) | `logging/` | In `openshift-logging`: ObjectBucketClaim `logging-loki`, a sync Job that builds Secret `logging-loki-s3` from it, LokiStack `logging-loki` (`1x.demo`, 3-day retention), Vector `ClusterLogForwarder` `box1` |
| `observability-dashboards` (2) | `dashboards/` | Perses datasource `box1-thanos-querier` (default) and dashboard `box1-order-flow`, shown under Observe → Dashboards |
| `observability-console` (2) | `console/` | `UIPlugin`s `distributed-tracing` (Observe → Traces), `logging` (Observe → Logs), `troubleshooting-panel` (korrel8r), and Argo CD access to UIPlugins |

All six Applications are manual-sync, like the other platform Applications.

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

## Edge-site logs and metrics (box1-docs#132)

The edge site VMs (`site-west` = `site_ds9`, `site-east` = `site_spacedock`) send OTLP logs and metrics to the same
collector, with resource attribute `site.id` (or `siteId`). Two pipelines in `tracing/collector.yaml` handle them; the
traces pipeline is unchanged.

- **Scope:** both pipelines drop every record whose `site.id` is not a known site, so services cannot use them by
  accident. Adding a site means adding it to `filter/site` and `transform/site-logs`.
- **Logs:** exported over OTLP/HTTP to the LokiStack gateway, application tenant
  (`/api/logs/v1/application/otlp`), with the service CA and the collector's token. ClusterRole
  `box1-collector-logs-write-application` (`tracing/rbac-logs.yaml`) grants the write. The collector sets the
  namespace from `site.id` (`site-west-dev`, `site-east-dev`) and `log_type: application`, so the openshift-logging
  tenancy applies: people who can view a site's namespace see its logs. Other resource attributes and the OTLP trace
  ID are stored as structured metadata, for example:

  ```logql
  {k8s_namespace_name="site-west-dev"} | site_id="site_ds9"
  {log_type="application"} | trace_id="<traceId>"
  ```

  Lines that look like they carry a credential are dropped (same pattern as `drop-credentials`).
- **Metrics:** a Prometheus exporter on port 8889. The operator adds port `prometheus` to Service `box1-collector`, a
  ServiceMonitor `box1-collector` for it, and the port to its own NetworkPolicy. Only `site.id`, `service.name` and
  `host.name` are kept as labels (`site_id`, `job`, `host_name`); series stop 5 minutes after a site stops sending.
  The metrics carry `namespace="box1-observability"`.
- **Not authenticated:** like traces, anyone who can reach port 4317/4318 can send records that claim a site.

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

## Logging

**Collection.** The Vector collector (`ClusterLogForwarder` `box1`) collects
application logs only from the seven Box1 service namespaces (`order-service-dev`,
`inventory-service-dev`, `fulfillment-adapter-dev`, `notification-service-dev`,
`asset-service-dev`, `scenario-controller-dev`, `operations-console-dev`).
Infrastructure and audit logs are not collected. Two filters run in order:

1. `drop-credentials` drops any line that looks like it carries a bearer token,
   password, client secret or private key. The services already redact at
   source; this is a backstop, and the dropped line is lost.
2. `parse-json` parses the services' JSON lines into `structured`.

**Storage.** LokiStack `logging-loki`, size `1x.demo`: one replica of each
component (two gateways), no CPU or memory requests, and four 10 Gi PVCs on
`lvms-vg1`. Chunks and index go to a dedicated NooBaa bucket (ObjectBucketClaim
`logging-loki`, kept if the Application is deleted). Retention is 3 days.

The `logging-loki-s3-sync` Job runs on every sync of `observability-logging`.
It reads the Secret and ConfigMap that NooBaa writes for the claim and writes
Secret `logging-loki-s3`, so no credential is stored in Git. The Job, not Argo
CD, owns that Secret. Its image is the cluster's `openshift/cli` release image,
pinned by digest; update it after a cluster upgrade.

**Query.** Observe → Logs in the console, or LogQL through the LokiStack
gateway. Tenant mode `openshift-logging`: a user sees application logs for
namespaces they can view; cluster admins see all. Example, all lines for one
order across services:

```logql
{log_type="application"} |= "ord_..." | json | structured_mdc_orderId="ord_..."
```

`structured_mdc_traceId` holds the trace ID. To open a trace's log lines, copy
the trace ID from Observe → Traces and use this console deep link (the logging
plugin reads `tenant` and `q` from the URL):

```text
https://<console>/monitoring/logs?tenant=application&q={log_type="application"} | json | structured_mdc_traceId="<traceId>"
```

**No one-click trace → log link exists yet.** The trace plugin has no logs
link. The troubleshooting panel's korrel8r trace store is fixed by the
operator to `tempo-platform` in `openshift-tracing`, which does not exist
here, and its trace rules only lead to Pods. The panel is still useful for
alerts, Pods and logs. Tracked in box1-docs#82.

**Service readers (box1-docs#111).** agentic-operations reads traces, logs
and alerts as evidence with its own ServiceAccount
(`agentic-operations-dev/agentic-operations`), read only:

- traces: `box1-agentic-operations-traces-read-dev` binds `box1-traces-read-dev`,
  and the `tempo-box1` NetworkPolicy admits its pods on 8080;
- logs: `box1-agentic-operations-application-logs` binds the logging operator's
  `cluster-logging-application-view` (`logging/rbac-readers.yaml`);
- which namespaces: ClusterRole `box1-observability-reader` (pods get/list,
  pods/log get) is bound only by RoleBindings in the Box1 service namespaces,
  kept with each service in box1-workloads-dev. It limits the Loki application
  tenant, the Thanos querier tenancy port (9092) and, with
  `monitoring-rules-view`, the Alertmanager tenancy port (9095) to those
  namespaces. Nothing grants it secrets, exec or cluster-wide metrics.

**Known risk: NooBaa (box1-docs#43).** NooBaa has one `pv-pool` backing store,
and its agent pod is not recreated after an eviction. While it is offline,
the ingesters cannot flush chunks and queries for older data fail. The
collector buffers and retries, then drops. Order and fulfillment do not depend
on logging.

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
4. Sync `observability-logging`. Check that the ObjectBucketClaim is
   `Bound`, the sync Job completed, the LokiStack reports `Ready`, and the
   collector DaemonSet is running.
5. Sync `observability-console`, then check that Observe → Traces lists
   `box1-observability/box1` with tenant `dev`, and Observe → Logs returns
   Box1 service logs.
6. Turn on trace export in each service in `box1-workloads-dev`.

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
- **Disable logging:** delete the `ClusterLogForwarder` `box1` (collection
  stops), then the `observability-logging` Application with cascade. This
  deletes the LokiStack PVCs. The ObjectBucketClaim `logging-loki` and Secret
  `logging-loki-s3` remain; delete them by hand to remove the bucket and its data.
  Remove the `logging` and `troubleshooting-panel` UIPlugins from `console/`.
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
