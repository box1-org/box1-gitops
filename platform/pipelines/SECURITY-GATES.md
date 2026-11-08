# Security-gate contract

`platform/pipelines/tasks/security-gates.yaml` is the reusable Tekton Task for
the Workstream 5C supply-chain checks. It binds every result to the full source
SHA, the exact `sha256` image digest, the service name, and the PipelineRun.

The Task has two external integrations:

- Syft **1.55.0** is downloaded by URL and checksum-verified, and must emit
  CycloneDX JSON **1.5**. The document is uploaded over TLS to RHTPA using the
  `rhtpa-ci` client. The referenced Secret is supplied as `rhtpa-secret` and
  contains only `client-secret`.
- `roxctl` **4.11.6** is downloaded from the RHACS mirror and checksum-verified.
  It runs `image scan` and `image check` against the exact digest. The
  referenced Secret is supplied as `rhacs-secret` and contains only
  `rox-api-token`.

The `enforcement` parameter is explicit. `observe` records the scan and policy
result and prints a rejection as an actionable report. `gate` fails the Task on
scanner failure or a non-passing RHACS policy. Missing credentials, invalid
provenance, checksum failures, upload failures, and timeouts always fail; no
scanner outage is treated as a pass. Reports are retained in the Task workspace
for the rest of the PipelineRun and the three Tekton results expose the SBOM
identifier, scan status, and policy status.

The Task is installed by the `pipelines-ci` Kustomization. Application release
definitions invoke it between `build` and `promote`. The Task's own
`enforcement` default stays `disabled`, but since box1-docs#42 the Quarkus
Golden Path template passes `security-gates=gate`, so new services block
promotion of a policy-failing image without extra configuration. Generated
services keep their own `.tekton/release.yaml`, so the template change does not
alter existing services; each sets its mode in that file. `observe` reports
without blocking, and `disabled` records an auditable no-op. Issue #9
still records RHACS registry integration, representative image scanning, policy
baseline, and admission violation testing as unverified. The enablement sequence
is:

1. Create the scoped `rhtpa-ci` and RHACS image-read/check credentials outside
   Git and verify TLS, registry access, and the exact-digest reports.
2. Run the Task with `enforcement=observe` for a representative release and
   record the RHTPA SBOM ID, RHACS scan/check output, source SHA, digest, and
   PipelineRun.
3. Define and test the application-namespace RHACS policy with a deliberately
   vulnerable image. Confirm the GitOps PR is not created or merged when
   `enforcement=gate` rejects it.
4. Repeat the remediated release through Argo and the existing runtime smoke
   checks.

Admission enforcement remains outside this Task. It must stay disabled for
OpenShift system namespaces until the controlled application-namespace denial
and rollback evidence required by issue #9 are published.

## RHACS registry access

`roxctl image scan` and `image check` ask Central to read the image, so Central
needs an image integration for
`image-registry.openshift-image-registry.svc:5000`. Without one, both return
`no matching image registries found`.

`ci/acs-registry-reader.yaml` declares the identity for that integration: the
`acs-registry-reader` ServiceAccount, `system:image-puller` in `box1-ci` only,
and the controller-populated `acs-registry-reader-token` Secret. The integration
itself is configured in Central, outside Git, because RHACS stores the token in
its own database. Rotate by deleting the Secret, syncing `pipelines-ci`, and
updating the integration's password.

## Trusting Central

`roxctl` verifies Central's certificate, which an internal RHACS CA signs. The
Task mounts `ci/rhacs-central-ca.yaml` and sets `ROX_CA_CERT_FILE`. If Central's
CA is rotated, update that ConfigMap from `stackrox/central-tls` key `ca.pem`.

## Known deviation: registry TLS

The RHACS integration for the internal registry has TLS verification disabled,
because Central does not trust the OpenShift service CA that signs the registry
certificate. The pull-only token therefore goes to an unverified endpoint inside
the cluster. Adding that CA to Central's trust would allow verification to be
turned back on. That change has not been made or tested.
