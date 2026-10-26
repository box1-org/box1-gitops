# Red Hat Advanced Cluster Security

RHACS 4.11.6 is deployed in `stackrox` on the Box1 cluster. Central and Scanner V4 use LVMS PVCs (`central-db` 20 GiB, `central-db-backup` 40 GiB, and `scanner-v4-db` 20 GiB) through the `lvms-vg1` StorageClass. Central is exposed at `https://acs.apps.ocp.box1.org`.

The Operator is GitOps-managed by `applications/acs-operator.yaml` from the `rhacs-4.11` channel with manual InstallPlan approval. Central and the Box1 SecuredCluster are managed by `applications/acs.yaml`. Admission enforcement is disabled and failure policy is fail-open for the initial monitoring rollout.

The cluster init bundle was generated with `roxctl` and applied directly as Kubernetes Secrets. The bundle and normalized runtime Secrets (`tls-cert-*`) are intentionally outside Git. Rotate or regenerate them through the RHACS Central UI/`roxctl`; do not commit Secret exports.

Observed validation on 2026-10-26 (America/New_York): the Operator CSV `rhacs-operator.v4.11.6` is `Succeeded`; Central, Central DB, legacy Scanner, Scanner V4 DB/Indexer/Matcher, Sensor, Admission Control, and Collector are running; the Central route returns HTTP 200; and the SecuredCluster reports `AVAILABLE=True` for RHACS 4.11.6.

Box1 currently reports OpenShift `5.0.0-rc.7`, Kubernetes `1.36.5`, and RHCOS 10.2. RHACS 4.11's published support matrix covers OCP 4.12, 4.14, 4.16, 4.18–4.22; vendor support for this Box1 combination is not established. This is a single-node lab deployment with deliberately reduced requests and one replica for constrained scheduling. Admission blocking, Keycloak OIDC, registry integration, representative image scan, policy tests, backup/recovery, and upgrade/rollback are follow-up validation; no production or HA claim follows.
