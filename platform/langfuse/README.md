# Langfuse

Self-hosted [Langfuse](https://langfuse.com) for LLM observability on Box1: traces, evaluations, prompt management
and datasets ([box1-docs#155](https://github.com/box1-org/box1-docs/issues/155)). Managed by the Argo CD Application
`langfuse` (`applications/langfuse.yaml`) from this directory.

| What | Value |
| --- | --- |
| UI, public API, OTLP ingestion | <https://langfuse.apps.ocp.box1.org> (edge TLS, cluster wildcard certificate) |
| Version | Langfuse 4.77.0 (`langfuse/langfuse`, `langfuse/langfuse-worker`), pinned by digest |
| Namespace | `langfuse` (Pod Security `restricted`) |
| Organisation / project | `box1` / `box1-default`, created by headless initialisation |

## Components

| Component | Image | Storage |
| --- | --- | --- |
| `langfuse-web` (UI, API; runs the PostgreSQL and ClickHouse migrations on start) | `docker.io/langfuse/langfuse` 4.77.0 | none |
| `langfuse-worker` (ingestion queue → ClickHouse, evals, exports) | `docker.io/langfuse/langfuse-worker` 4.77.0 | none |
| `langfuse-postgres` (users, orgs, projects, keys, prompts) | `registry.redhat.io/rhel9/postgresql-15` (OpenShift catalog) | `langfuse-postgres-data`, 10 GiB, `lvms-vg1` |
| `langfuse-clickhouse` (traces, observations, scores), single node | `docker.io/clickhouse/clickhouse-server` 26.3.62.3 | `langfuse-clickhouse-data`, 20 GiB, `lvms-vg1` |
| `langfuse-redis` (cache, BullMQ queues; `noeviction`, AOF) | `registry.redhat.io/rhel9/redis-7` (OpenShift catalog) | `langfuse-redis-data`, 2 GiB, `lvms-vg1` |
| S3 (event payloads `events/`, media `media/`) | NooBaa ObjectBucketClaim `langfuse-bucket` | NooBaa `pv-pool` backing store |

The ClickHouse version is the one Langfuse 4.77.0's reference `docker-compose.yml` uses. All instances are single
replica on node-local storage: the PVCs are not backups. The PostgreSQL and ClickHouse PVCs and the bucket claim are
kept when the Application is deleted (`Prune=false,Delete=false`).

Web and worker reach NooBaa through `https://s3.openshift-storage.svc` and trust the OpenShift service CA
(`langfuse-service-ca`, injected, via `NODE_EXTRA_CA_CERTS`). SDKs and browsers get presigned media URLs on the public
route `https://s3-openshift-storage.apps.ocp.box1.org`.

## Sign-in and roles

- **Keycloak SSO** (realm `box1`, confidential client `langfuse`,
  `platform/identity/keycloak/realm/langfuse-client.yaml`). A realm user's first sign-in creates their Langfuse user
  and adds them to org `box1` and project `box1-default` as **Viewer**. Users need an email address in the realm.
  Raise a person's role in Langfuse (*Organization settings → Members*); realm roles are not mapped.
- **Local owner** `langfuse-admin@box1.local`: created at first start as Owner of org `box1`; the only account
  allowed to create organisations. For administration and break-glass when Keycloak is unavailable. Read its
  password from the cluster only when needed:

  ```bash
  oc get secret langfuse-secrets -n langfuse -o jsonpath='{.data.LANGFUSE_INIT_USER_PASSWORD}' | base64 -d
  ```

- **Local self-signup is closed** by the `langfuse-signup-disabled` Route, which sends `/api/auth/signup*` to a
  Service without endpoints (503). Langfuse's `AUTH_DISABLE_SIGNUP` is not used because it also refuses first-time
  SSO users. Invite additional local accounts only if SSO is unsuitable.

## Sending traces

The initial project's API keys are in `langfuse-secrets` (`LANGFUSE_INIT_PROJECT_PUBLIC_KEY`,
`LANGFUSE_INIT_PROJECT_SECRET_KEY`). Create further keys per application in the UI (*Project settings → API Keys*).

```bash
export LANGFUSE_HOST=https://langfuse.apps.ocp.box1.org
export LANGFUSE_PUBLIC_KEY=pk-lf-...   # from the UI or langfuse-secrets
export LANGFUSE_SECRET_KEY=sk-lf-...
```

OpenTelemetry exporters use `https://langfuse.apps.ocp.box1.org/api/public/otel` with HTTP basic auth
(public key : secret key). In-cluster callers also use the public route: the NetworkPolicies admit only the router
to `langfuse-web`, and only the Langfuse pods to the databases.

## Credentials

No credential is stored in Git. The `langfuse-bootstrap` Job (Argo CD Sync hook, `bootstrap.yaml`) runs on every sync:

- `langfuse-secrets` is **generated once and never overwritten**: `DATABASE_PASSWORD`, `CLICKHOUSE_PASSWORD`,
  `REDIS_AUTH`, `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY`, `LANGFUSE_INIT_USER_PASSWORD`,
  `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY`. The Job fails if a key is missing.
- `langfuse-keycloak` is copied on every sync from `keycloak/keycloak-client-secret-langfuse`, which the RH-SSO
  operator generates. A Role in `keycloak` lets the Job read only that Secret.
- S3 credentials stay in NooBaa's `langfuse-bucket` Secret and ConfigMap, read directly by web and worker.

`langfuse-secrets` must be preserved with the volumes: `SALT` hashes the stored API keys, `ENCRYPTION_KEY` encrypts
stored LLM connection keys, and the database passwords are baked into the initialised PostgreSQL and ClickHouse data.
Back it up before any destructive operation; do not commit an export.

## Operations

- **Status:** `oc get pods,pvc,obc,route -n langfuse`; health at `/api/public/health` (web) and `/api/health`
  (worker, port 3030, in-cluster only).
- **Upgrade:** change the web and worker digests together (same release); Langfuse applies its migrations on web
  start. Read the release notes for ClickHouse or PostgreSQL version requirements first.
- **Rotate the Keycloak client secret:** regenerate it in Keycloak, then sync `langfuse` (the Job copies it) and
  restart `langfuse-web`.
- **Restart order after an outage:** the datastores first; web and worker retry until they are reachable.
- **Removal:** delete `applications/langfuse.yaml`. Argo CD prunes the workloads; the PostgreSQL and ClickHouse PVCs,
  the bucket claim, `langfuse-secrets` and `langfuse-keycloak` remain until deleted by hand. Remove the client from
  `platform/identity/keycloak/realm/` separately.

## Limitations

- Single replica of every component on node-local storage; no backups are configured.
- NooBaa uses one `pv-pool` backing store; while it is unavailable (box1-docs#43), Langfuse cannot store event
  payloads or media.
- Batch exports to S3 are disabled. The optional Langfuse AI gateway is not deployed.
