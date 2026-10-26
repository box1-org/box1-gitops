# Box1 Trusted Profile Analyzer

RHTPA 3.1.1 is deployed at <https://tpa.apps.ocp.box1.org> in namespace
`trusted-profile-analyzer`. Sign in through the existing Keycloak `box1` realm.
Tracking and acceptance: [box1-docs #8](https://github.com/box1-org/box1-docs/issues/8).
Pipeline automation is [workstream 5C / #10](https://github.com/box1-org/box1-docs/issues/10).
This service supplies analysis and reporting; it does not block builds.

## Versions and compatibility

- Box1: OpenShift 5.0.0-rc.7, Kubernetes 1.36.5, one node. The RHTPA Operator
  installed successfully; **vendor support for this combination is not established**.
- Red Hat RHTPA Operator 3.1.1, `stable-v3`, manual InstallPlan approval.
  The existing August 3 snapshot catalog offered only 3.0.0. A separate
  `rhtpa-redhat-current` catalog supplies 3.1.1 without changing existing subscriptions.
  Its observed Red Hat v4.22 index digest is pinned in `operator/catalog.yaml`.
- RHTPA server/importer image:
  `registry.redhat.io/rhtpa/rhtpa-rhel10@sha256:0f696e6f7ceadc6f4a2891eb4d65d375f241275da52127e0dcb302806b2a0292`.
- PostgreSQL 15, Red Hat RHEL 9 image, digest pinned in `prerequisites/postgres.yaml`.
  It is dedicated to RHTPA. Application credentials are separate from the PostgreSQL
  administrator used by the Operator's database migration job.
- Existing NooBaa supplies S3, existing LVMS supplies block volumes, existing
  cert-manager/Let's Encrypt supplies the public certificate. Successful image pulls
  establish registry access, not an independent entitlement or support determination.

[Red Hat 3.1 deployment guide](https://docs.redhat.com/en/documentation/red_hat_trusted_profile_analyzer/3.1/html-single/deployment_guide/index)
recommends an initial 4 CPUs, 8 GB memory and 45 GB each for database and object
storage. This single-node lab requests 500m CPU / 8 GiB for the server, 1 CPU /
8 GiB for the importer, and 250m / 512 MiB for PostgreSQL; memory ceilings are
12 GiB, 12 GiB and 4 GiB respectively. No CPU limit is imposed on these workloads.
The server's request was reduced from 1 CPU after a surge pod could not fit the
node's CPU reservations despite low actual utilization. This permits rolling
updates without reducing other workloads' reservations. It is not a load test.

PostgreSQL has a protected 45 GiB RWO PVC on `lvms-vg1`; the importer has an
8 GiB ephemeral work PVC, whose contents are a disposable advisory-repository
cache. The OBC allocates a dedicated unversioned bucket in existing NooBaa;
it does not reserve another 45 GiB of object capacity. Check NooBaa capacity
before increasing inventory. Node-local LVM and this single database provide no HA.

## Management and installation order

Three manual-sync Argo CD Applications in `applications/` are discovered by
`box1-root`: `rhtpa-operator`, `rhtpa-prerequisites`, and `rhtpa`.
They deliberately have no pruning or resources finalizer.

1. Sync `rhtpa-operator`. Review the generated plan for `rhtpa-operator.v3.1.1`,
   approve that plan, and wait for CSV Succeeded. The Operator watches only this
   namespace. Future upgrades remain manual; changing the catalog digest is a
   separate reviewed action, and `startingCSV` alone is not a version lock.
2. Run `python3 validation/bootstrap.py` with cluster access and trusted access to
   the existing Keycloak endpoint. It creates database/CI Secrets directly, without
   printing credentials or storing last-applied plaintext. It reconciles the two
   dedicated Keycloak clients and grants the existing `mike` account `rhtpa-admin`.
   Keycloak clients/role are managed by this bootstrap script through the Admin API,
   not by the legacy Keycloak Operator. Realm identity data remains in Keycloak's DB.
3. Bootstrap `prerequisites/gitops-access.yaml` once as cluster administrator.
   It grants the Argo controller namespace-scoped mutations of the named resource
   types used by these Applications, without granting Secret reads or writes.
4. Sync `rhtpa-prerequisites`; wait for PostgreSQL Ready, OBC Bound, Certificate Ready,
   and the database-grants PostSync job Complete. It grants application permissions
   on existing and future tables/sequences created by the migration administrator.
5. Check the OBC's generated bucket name and update `instance/rhtpa.yaml` when
   provisioning a new bucket. The committed name is the actual Box1 bucket identifier,
   not a credential. Sync `rhtpa`; wait for Deployed=True and server/importer Ready.
   The Operator owns its Helm release, migration jobs and runtime resources.
6. The `rhtpa` PostSync job applies the importer SQL ConfigMap. It changes a source
   only when its configuration differs and resets its success marker so expanded
   coverage is reprocessed. Sources are daily. The initial full GitHub import can
   take tens of minutes; inspect progress and final report before claiming freshness.

The chart's default disabled OSV entry lacks `transport`, which its own schema
requires. The CR explicitly supplies `transport: git` to satisfy schema validation.
The pinned runtime uses Git-based OSV import. Importer definitions are maintained
by the explicit PostSync job because changing only the Operator chart's completed
setup hook did not rerun that hook. `modules.createImporters.enabled` is false.
The custom authentication ConfigMap is external because the chart's string form
failed template evaluation. Use `ingress.hosts`, not unsupported `ingress.host`.
The Operator status message prints its default `server.apps...` hostname; the
actual Ingress and verified URL are `tpa.apps.ocp.box1.org`.

## Authentication, credentials and rotation

- `rhtpa-frontend`: public Authorization Code client, S256 PKCE, only the TPA HTTPS
  redirect/origin. Password grants, implicit flow and service accounts are disabled.
  Authenticated realm users can read inventory. The `rhtpa-admin` realm role permits
  document/importer administration; the bootstrap assigns it to existing `mike`.
- `rhtpa-ci`: confidential service-account client; interactive and password grants
  are disabled. Its audience is `rhtpa-ci`. The application grants only `create.sbom`,
  `read.sbom` and `read.metadata`; advisory and importer administration are denied.
  Advisory findings are viewed by authenticated users through the frontend.
- `rhtpa-database`: `password` for database user `trustify`, `admin-password` for
  migration user `postgres`. Database traffic stays within the namespace and uses
  PostgreSQL `sslMode: disable`. The external UI, OIDC and S3 calls validate TLS.
- `rhtpa-documents`: OBC controller-managed access/secret keys. The dedicated account
  can access this bucket, and access to unrelated `first.bucket` was rejected.
- `rhtpa-ci`: `client-id`, `client-secret`, `issuer-url`. No credential is committed.

For CI, copy only its dedicated client credential to the pipeline namespace through
an authorized secret-management workflow. Do not grant builds Keycloak administrator
or RHTPA namespace-wide Secret access. `validation/upload-sbom.py` accepts
`RHTPA_CLIENT_SECRET`, optional `RHTPA_CLIENT_ID`, `RHTPA_ISSUER` and `RHTPA_URL`.
Use it after Syft generates CycloneDX JSON 1.5; pass the full source commit, exact
sha256 image digest, service and source repository. It labels the record and expects
HTTP 201. Never put tokens or client secrets into PipelineRun parameters or logs.
This upload contract is ready for #10; automatic per-build SBOM integration is not
implemented by this platform deployment.

Rotation procedures (not exercised): rotate the CI secret in Keycloak, update the
out-of-Git RHTPA/pipeline Secret consumers, and verify upload plus negative access
checks. For database passwords, coordinate SQL role changes, Secret updates and
PostgreSQL/server/importer restarts; Secret edits alone do not alter existing SQL
roles. Preserve both passwords through recovery. For S3, use NooBaa-supported account
key rotation and update OBC credential consumers; avoid deleting/recreating the OBC
as a rotation shortcut. The Operator may not restart pods on an external Secret or
auth ConfigMap change; explicitly perform and verify a controlled restart. Do not
silently broaden CI permissions during rotation.

## Validation and limits

Observed 2026-10-25, America/New_York:

- Operator 3.1.1 Succeeded; dedicated PostgreSQL Ready; migration job Complete;
  RHTPA Deployed=True; server and importer Ready; Let's Encrypt Certificate Ready.
- The user completed a real browser Keycloak login and the inventory interface loaded.
- TLS-verified anonymous SBOM API request: 401. CI token: SBOM read 200, upload 201;
  importer read and advisory upload 403.
- Syft 1.55.0, release checksum verified, scanned the exact deployed reference image:
  `sha256:75caa059d31734251fadc93afee730ba2e9d976de007aebfe33e6e9546e8ecf8`.
  Matching Tekton run `box1-ci/quarkus-release-5z59z` recorded source revision
  `640b029c657eaacebacc46aa63894f2276d57f1d`. The source image's inherited base-image
  OCI revision was not mistaken for the application revision.
- CycloneDX 1.5 accepted: 6,554 serialized components, including 6,270 file entries,
  283 libraries and one operating-system entry. RHTPA displays 285 inventory entries
  including the root image. The API exposes Maven/RPM dependencies and license IDs,
  including Apache-2.0 and LGPL-2.1-or-later.
- Record: `urn:uuid:01a17648-2d52-769a-9996-e1303b7c0a63`. Digest/source labels were
  read back through the API and appeared in the signed-in browser.
- A controlled server restart produced a new Ready pod; full original SBOM download
  returned 200 with unchanged SHA-256
  `9b9d0f23dcbb837d6b1c7b89afea216f34914ff2411c5d9c5c7b336f1eac2714`.
- Dedicated S3 list/download succeeded with TLS verification; unrelated bucket list
  returned 403. The original SBOM's object hash matched. A local diagnostic database
  archive and S3 object copy were made while ingestion continued; **these are not a
  coordinated disaster-recovery backup** and are not stored in Git.

`osv-github` imports all years of GitHub's reviewed advisory repository.
`redhat-csaf-sample` deliberately selects three signed RHSA documents; it is not
full Red Hat coverage. Filters match the filename basename, not a URL/path.
Other chart-default importers remain disabled. A successful importer run with
zero documents does not establish coverage. See the recorded evidence for final
run counts, freshness, findings and any outstanding VEX/history checks. Zero
findings before source import completes must not be treated as a clean assessment.

## Backup and recovery

Full restore, credential rotation and uninstall are **not tested**. PVC/OBC retention
annotations protect against Argo pruning; LVMS and NooBaa use Delete reclaim policy,
so direct deletion can destroy data. A PVC is not a backup.

Use this coordinated recovery procedure; it is documented but not exercised:

1. Schedule a brief maintenance window. Stop ingestion clients and set server
   readOnly=true in Git. Stop the importer through the CR and verify no active
   importer writes; retain the OBC, PostgreSQL PVC, Secrets and Keycloak data.
   Stopping the importer discards its ephemeral clone cache; the DB holds run history.
2. Use `kubectl exec -n trusted-profile-analyzer deploy/rhtpa-postgres -- pg_dump
   -U postgres -Fc trustify` to save a consistent logical dump to a protected file.
   Use `validation/s3-check.py --backup-dir <protected-directory>` to copy all bucket
   objects and a key/filename/SHA-256 manifest while writes remain stopped. Verify
   dump readability using `pg_restore -l` in a compatible PostgreSQL container.
3. Back up the three credential Secrets and OBC credentials through the lab's
   approved encrypted secret-backup mechanism; do not place exports in Git. Back up
   Keycloak's database separately. Copy dump, objects/manifest and credentials to an
   independent encrypted destination, record checksums and the Git/image revisions,
   and verify that destination before restarting ingestion.
4. For recovery, provision an isolated namespace/database/bucket first. Restore the
   SQL archive with matching PostgreSQL tools and owners; restore S3 object bytes
   using the manifest's original keys and verify checksums. Use the dedicated OBC
   account rather than a global NooBaa administrator. This repository's Python checker
   implements reads/backups only; use an S3-capable recovery tool for object uploads.
5. Restore Secrets, update the CR's actual bucket/database endpoint, restore the
   matching Operator/runtime images and Git revision, then reconcile in installation
   order. Verify authenticated SBOM download, dependency and finding queries, content
   hashes, anonymous 401 and scoped-client 403 before switching the public endpoint.
6. Resume ingestion only after the recovered data is verified. Preserve the original
   volumes/bucket until the replacement is accepted. A major schema upgrade needs a
   version-specific migration and compatible restore; reverting an image alone is
   not a database rollback.

To stop or remove the installation, first disable/remove its child Applications
from root discovery so GitOps cannot recreate them. Stop the RHTPA CR workloads,
then review the Red Hat version-specific Operator uninstall procedure. Preserve
PVC, OBC, credentials and backups; delete retained data only with separate explicit
authorization. Do not remove shared Keycloak, cert-manager, LVMS, NooBaa or catalogs
used by other subscriptions. Remove only the dedicated clients and namespace-scoped
GitOps access when their consumers no longer need them.
