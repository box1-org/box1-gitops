# Developer Hub platform connection verification

Verified on 2026-10-25 against the live box1 cluster. Definition of done met.

The committed `scripts/verify-connections.cjs` queried the actual catalog entities, then the Hub Kubernetes and Argo CD backend APIs using a five-minute signed automation JWT. No browser was used.

| Catalog entity | Deployments | PipelineRuns | TaskRuns | Argo CD |
| --- | ---: | ---: | ---: | --- |
| `quarkus-reference` | 1 | 7 | 15 | Synced / Healthy |
| `orders-service` | 1 | 4 | 10 | Synced / Healthy |

Both returned cluster `box1`, workload Pods in their deployment namespace, matching Routes, CI runs in `box1-ci`, and the selector-matched Argo CD Application. Kubernetes backend error arrays were empty. Counts are a point-in-time observation; publishing service metadata triggered normal CI and those additional runs are included.

Permission boundaries verified:

- Kubernetes `list secrets` across namespaces: denied.
- Kubernetes `create deployments` in `orders-service-dev`: denied.
- Argo CD `applications/get/default/quarkus-reference`: allowed.
- Argo CD `applications/sync/default/quarkus-reference`: denied.
- Argo CD `applications/delete/default/quarkus-reference`: denied.

`developer-hub`, `developer-hub-gitops-access`, `quarkus-reference`, and `orders-service` Applications were all Synced and Healthy. Hub rollout completed. Both Kustomize targets passed server dry runs, all four Golden Path render cases passed, unsafe names were rejected, and changed repositories passed whitespace checks.

Credentials remain in Kubernetes Secrets. The Hub uses the dedicated reader ServiceAccount and dedicated Argo CD API account; administrative bootstrap access is never configured as a runtime connection. TLS verification remained enabled.

The Argo CD token expires after 90 days. Rotation and trust-refresh instructions are in [README.md](README.md#live-platform-connections). The existing Kubernetes service-account token Secret is long lived and must be explicitly rotated as described there.

Published implementation commits: `box1-gitops` ab4cfa8, `box1-templates` 7d38ec3, `orders-service` 519691c, `quarkus-reference` d8431b7. This evidence and the final verifier authentication/permission checks are recorded by a follow-up commit.
