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

The Task is installed by the `pipelines-ci` Kustomization, but application
release definitions do not invoke it yet. Issue #9 still records RHACS registry
integration, representative image scanning, policy baseline, and admission
violation testing as unverified. Until those checks are completed, wiring this
Task into promotion would either require unreviewed credentials or make every
release fail before the existing GitOps flow. The enablement sequence is:

1. Create the scoped `rhtpa-ci` and RHACS image-read/check credentials outside
   Git and verify TLS, registry access, and the exact-digest reports.
2. Run the Task with `enforcement=observe` for a representative release and
   record the RHTPA SBOM ID, RHACS scan/check output, source SHA, digest, and
   PipelineRun.
3. Define and test the application-namespace RHACS policy with a deliberately
   vulnerable image. Confirm the GitOps PR is not created or merged when
   `enforcement=gate` rejects it.
4. Wire the Task between `build` and `promote` in the generated template and
   existing application release Pipelines, then repeat the remediated release
   through Argo and the existing runtime smoke checks.

Admission enforcement remains outside this Task. It must stay disabled for
OpenShift system namespaces until the controlled application-namespace denial
and rollback evidence required by issue #9 are published.
