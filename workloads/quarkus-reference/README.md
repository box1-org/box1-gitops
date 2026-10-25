# Quarkus reference runtime

Argo CD's `quarkus-reference` child Application owns this workload. Its desired
image is pinned by digest in `kustomization.yaml`; the runtime pulls from Box1's
existing internal OpenShift registry, not from a public application registry.
The build source and manual Tekton pipeline are in
[box1-org/quarkus-reference](https://github.com/box1-org/quarkus-reference).

The root app-of-apps registers the Application. Automatic sync/self-heal deploys
Git state; automatic pruning is disabled, consistent with the platform's existing
policy. Never use a Tekton task to apply these resources to the cluster.

## Resources

- Dedicated namespace and ServiceAccount; no mounted Kubernetes API token.
- One JVM replica, non-root under OpenShift's restricted SCC, read-only root
  filesystem, bounded writable `/tmp`, dropped capabilities and resource limits.
- Startup, readiness and liveness HTTP probes using SmallRye Health.
- Service on port 8080 and HTTPS Route at
  https://quarkus-reference.apps.ocp.box1.org, with HTTP-to-HTTPS redirect.
- Kustomize-generated ConfigMap supplying `GREETING_PREFIX` and JVM memory flags.
  Its content hash is reflected in the Pod template, so config changes roll out.
- The pull binding lives in `platform/pipelines/ci/quarkus-reference-pull.yaml`
  because permission must be granted in the source image project, `box1-ci`.
  Only `quarkus-reference/quarkus-reference` receives that cross-project pull grant.

## Update and verify

1. Build a source commit through the application's manual Tekton PipelineRun.
   Require unit/HTTP tests to pass and record the emitted `image-digest` result.
2. Change the digest in this Kustomization and publish through Git review.
   Record the source SHA and PipelineRun alongside the desired image.
3. Wait for Argo CD to report Synced/Healthy, verify the Deployment is Available,
   and run `scripts/smoke.py` from the source repository against the HTTPS Route.

```sh
kubectl kustomize workloads/quarkus-reference
kubectl -n openshift-gitops get application quarkus-reference
kubectl -n quarkus-reference rollout status deployment/quarkus-reference
kubectl -n quarkus-reference get pods,service,route,configmap
```

Rollback by reverting the desired digest in Git. Do not replace it with a mutable
tag or change the Deployment directly. This reference has no application data or
persistent runtime volume. See `VERIFICATION.md` for the initial delivery evidence.
