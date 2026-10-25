# Phase 2 delivery evidence

Verified 2026-10-24, America/New_York. The exit criterion is met: the reference
application is healthy and accessible through its OpenShift HTTPS Route, with
all desired runtime resources tracked in Git and deployed by Argo CD.

## Application and build

- Repository: [box1-org/quarkus-reference](https://github.com/box1-org/quarkus-reference).
- Built source: [`ccbe55842dd3445848a22475662f19cb5c0ad2a6`](https://github.com/box1-org/quarkus-reference/commit/ccbe55842dd3445848a22475662f19cb5c0ad2a6).
- Generated Quarkus 3.40.1.1, Java 21, Maven 3.9.16.
- Tekton PipelineRun: `box1-ci/quarkus-reference-build-mwr69`, Succeeded=True.
- Three plain unit tests, four Quarkus HTTP tests, and four packaged JVM HTTP
  integration tests passed: **11 tests, zero failures/errors/skips**.
- Jib pushed only after `verify -DskipITs=false` succeeded. No Docker daemon,
  Docker socket, privileged container or native compiler was used.
- Digest-pinned UBI 9 OpenJDK 21 builder and runtime images. Build Pod admitted
  under OpenShift `restricted-v2`, with an assigned non-root UID.
- The minimal UBI builder has no unzip binary. The fetch step validates and
  extracts the exact Maven ZIP using the SHA-256 in the wrapper properties;
  checksum validation was retained.

Published image:

```text
registry.apps.ocp.box1.org/box1-ci/quarkus-reference@sha256:62b2c49fa223e679c9062b9b93175ced4281e684dd13e77560a59b50a251740e
```

The source-fetch credential was a repository-scoped Contents-read installation
token from the dedicated Pipelines App. It was revoked and the temporary
`box1-ci/quarkus-reference-source` Secret deleted after the build. The Maven
step did not receive that GitHub token. Registry push used the existing
`ci-build` identity and verified TLS at the registry Route.

## GitOps delivery

- Initial desired-state commit:
  [`043df66a7a6d56725cddfb546cf575d5f8698c0c`](https://github.com/box1-org/box1-gitops/commit/043df66a7a6d56725cddfb546cf575d5f8698c0c).
- Argo CD Application `openshift-gitops/quarkus-reference`: Synced / Healthy.
  Registered by the existing root app-of-apps and deployed by automated sync.
- Deployment tracking ID:
  `quarkus-reference:apps/Deployment:quarkus-reference/quarkus-reference`.
- Deployment: one available replica. Pod Ready=True, zero restarts at inspection,
  `restricted-v2` SCC, read-only root filesystem, API-token automount disabled.
- Runtime ServiceAccount: `quarkus-reference/quarkus-reference`. Scoped pull
  binding in `box1-ci`; an impersonated check confirmed image-layer update
  permission is denied. No runtime registry push privilege.
- Running imageID exactly matched the published digest above, using the internal
  `image-registry.openshift-image-registry.svc:5000` endpoint.
- ConfigMap `quarkus-reference-config-2k8m875fkk`, generated from tracked literals.
  Greeting and JVM memory settings were observed in the application.
- Deployment, Service, Route, ConfigMap generator, startup/readiness/liveness
  probes, ServiceAccount and namespace are tracked in the runtime Kustomization.
  The pull RoleBinding is tracked in the platform CI Kustomization.
- The Route is Admitted=True, with edge TLS and HTTP-to-HTTPS redirect.
- No application manifest was applied manually or by a Tekton deployment task.

## External HTTP smoke test

Route: https://quarkus-reference.apps.ocp.box1.org

Executed the repository's `scripts/smoke.py` against the real Route with normal
TLS certificate verification. Passed:

- `/api/greetings?name=OpenShift` returned JSON message
  `Hello from box1, OpenShift!`, proving the ConfigMap value was consumed.
- `/api/info` reported Java major version 21.
- `/q/health/live`, `/q/health/ready`, `/q/health/started` returned HTTP 200 / UP.
- `/q/openapi` returned a JSON schema containing both REST endpoints.
- `/q/metrics` exposed `box1_greetings_total` after the greeting request.
- A blank greeting name returned HTTP 400.

The runtime log reported Quarkus 3.40.1.1 starting in 1.293 seconds. All existing
platform Argo CD Applications remained Synced / Healthy at final inspection.

The manual reference path is complete. Self-service scaffolding, automatic
application CI triggers, cross-repository GitOps image PR automation, and
untrusted PR isolation remain later phases. Native builds are deferred.
