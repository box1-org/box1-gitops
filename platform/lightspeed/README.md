# OpenShift Lightspeed on Box1

OpenShift Lightspeed Operator **2.0.0** (`redhat-operators`, channel `stable`)
with the console assistant backed by the in-cluster vLLM server.

| Item | Value |
| --- | --- |
| Namespace | `openshift-lightspeed` |
| Operator | `lightspeed-operator.v2.0.0`, manual InstallPlan approval |
| LLM provider | `box1-vllm`, type `rhoai_vllm` |
| Endpoint | `http://vllm-test-2.vllm.svc.cluster.local:8000/v1` (internal Service only) |
| Model | `box1-coder` (vLLM `--served-model-name`; checkpoint `nvidia/Qwen3.8-27B-NVFP4`) |
| Context / response | 98304 tokens (matches vLLM `--max-model-len`) / 4096 tokens |

Lab-only on OpenShift 5.0.0-rc.7; vendor support for this combination is
**not established**.

## GitOps ownership

- `applications/lightspeed-operator.yaml` → `platform/lightspeed/operator`
  (Namespace, OperatorGroup, Subscription). The operator was first installed
  from the console; the OperatorGroup keeps its generated name
  `openshift-lightspeed-bnj2t` so Argo CD adopts it rather than creating a
  second OperatorGroup (which would break OLM).
- `applications/lightspeed.yaml` → `platform/lightspeed/config`
  (Argo CD RBAC for `olsconfigs`, and the `OLSConfig/cluster`).
- Both Applications are manual-sync, discovered by `box1-root`.

## Out-of-band prerequisite: credentials Secret

`OLSConfig` requires a provider credentials Secret with an `apitoken` key.
The vLLM server does not currently enforce an API key, so the value is a
placeholder. It is not stored in Git:

```bash
oc -n openshift-lightspeed create secret generic box1-vllm-credentials \
  --from-literal=apitoken=unused-vllm-has-no-auth
```

If API-key auth is added to vLLM (box1-org/box1-docs#26), replace the value
with the real key; the operator restarts the service on Secret change.

## Capacity caveat

`vllm/vllm-test` runs with `--max-num-seqs 1` on the single RTX 5090 and is
shared with other Box1 consumers, so Lightspeed requests queue behind (and
delay) other inference traffic.

## Rollback

- Remove the LLM wiring: delete `OLSConfig/cluster` (sync `lightspeed` with
  prune, or `oc delete olsconfig cluster`). The operator removes the
  app-server, console plugin and Postgres it created.
- Uninstall the operator: delete the Subscription and the
  `lightspeed-operator.v2.0.0` CSV in `openshift-lightspeed`.
