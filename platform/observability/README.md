# Box1 observability (`operate` profile)

Distributed tracing and user-workload monitoring for Box1, from
[box1-docs#22](https://github.com/box1-org/box1-docs/issues/22). Nothing here
uses object storage. Centralized logging is deferred to
[box1-docs#82](https://github.com/box1-org/box1-docs/issues/82).

| Application (sync wave) | Path | Creates |
|---|---|---|
| `observability-operators` (0) | `operators/` | Red Hat build of Tempo and Red Hat build of OpenTelemetry operators, `stable` channel, manual InstallPlan approval |
| `user-workload-monitoring` (0) | `user-workload-monitoring/` | `cluster-monitoring-config` with `enableUserWorkload: true` |
| `observability-tracing` (1) | `tracing/` | Namespace `box1-observability`, `TempoMonolithic` `box1` (10 Gi PV on the default class, 72 h retention, Jaeger UI behind OpenShift OAuth, reencrypt Route), `OpenTelemetryCollector` `box1`, NetworkPolicies |

All three Applications are manual-sync, like the other platform Applications.

## Data path

Services export OTLP to `box1-collector.box1-observability.svc:4317` (gRPC)
or `:4318` (HTTP). The collector batches, limits memory and forwards to
`tempo-box1:4317`. Tempo accepts spans only from the collector. Its query
API is reachable only inside the namespace and through the Jaeger UI Route,
which requires an OpenShift login with permission to get pods in
`box1-observability`.

## Install order

1. Sync `observability-operators`. Approve the two InstallPlans after checking
   their CSV versions, then wait for both CSVs to report `Succeeded`.
2. Sync `user-workload-monitoring`. Wait for the Prometheus and Thanos Ruler
   pods in `openshift-user-workload-monitoring` to be ready.
3. Sync `observability-tracing`. Wait for the TempoMonolithic `Ready`
   condition, the `tempo-box1` PVC to bind, and the collector Deployment.
4. Turn on trace export in each service in `box1-workloads-dev`.

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
