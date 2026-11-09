# Reposilite Maven proxy

In-cluster caching proxy of Maven Central for Box1 CI
([box1-docs#113](https://github.com/box1-org/box1-docs/issues/113)). Tekton build
pods are throwaway and keep no local Maven repository, so before this proxy every
Quarkus build downloaded about 180–270 MB from Maven Central. When Central
rate-limited the cluster (HTTP 429) on 2026-11-08, releases failed for hours.

- **Endpoint:** `http://reposilite.box1-maven.svc:8080/maven-central`. It is
  cluster-internal: there is no Route, and the NetworkPolicy admits only `box1-ci`.
- **Repository:** one repository, `maven-central`, proxying
  `https://repo.maven.apache.org/maven2` with `store: true`. Each artifact is
  fetched from Central once, then served from the 5 Gi PVC `reposilite-data`.
- **Configuration:** `shared-configuration.json`, mounted read-only from a
  generated ConfigMap. Git is the only source of truth; the dashboard cannot
  change repositories. Editing the file rolls the pod.
  - `allowedExtensions` must stay empty, which allows all extensions.
    Reposilite's default list rejects Quarkus platform `.properties` artifacts
    and breaks every Quarkus build.
- **Access:** anonymous read only. No access tokens exist and nothing is
  deployed to this instance.
- **Consumers:** the `box1-quarkus-maven` Task downloads Maven 3.9.16 (checksum
  still pinned in the Task) and resolves all dependencies through this endpoint,
  using a platform-written `settings.xml` with `<mirrorOf>*</mirrorOf>`.
- **Transport:** plain HTTP inside the cluster. Maven still verifies artifact
  checksums, but those come from the same server, so integrity rests on the
  NetworkPolicy and cluster network. In-cluster TLS (service CA) is a possible
  follow-up.

## Behaviour and limits

- **First fetch is slower:** an artifact the cache has never seen is fetched
  from Central during the build. A cold quarkus-reference build through the
  proxy took about 158 s on a workstation, versus 29 s direct. Later builds are
  served from the PVC (fulfillment-adapter: 34 s through a warm proxy, versus
  50 s direct with no cache).
- **Outage behaviour:** builds succeed while Central is unreachable if every
  artifact they need is already cached. This was verified on a workstation
  with the upstream pointed at a closed port. A new dependency or version still
  needs Central once.
- **Single point of failure:** there is one replica, and Maven mirrors do not
  fall back to Central. If Reposilite is down, Maven builds fail fast with
  connection errors.
- **Losing the cache is safe:** if the PVC is lost, the cache refills from
  Central on the next builds. No other data lives here.
- **No automatic eviction:** the cache grows with every new dependency
  version. Check usage with
  `oc -n box1-maven exec deploy/reposilite -- du -sh /app/data`.
  To reset it, delete the PVC and restart the pod; the cache then refills.

## Rollout

The `reposilite` Application syncs automatically. Sync it and wait for the pod
to be ready **before** syncing `pipelines-ci` with the Task change. Otherwise
Maven builds fail to reach the mirror.

Warm the cache once, for example by re-running one release per service, and
check that a second run makes no requests to `repo.maven.apache.org`.

## Rollback

Revert the `platform/pipelines/tasks/quarkus-maven.yaml` change and sync
`pipelines-ci`. Builds then download from Maven Central directly again.
The proxy itself can stay in place or be removed with its Application.
