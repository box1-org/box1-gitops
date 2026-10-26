# Development workload repository split

Target: `box1-org/box1-workloads-dev`. Platform source baseline:
`box1-org/box1-gitops@f682e73`.

## Ownership

The platform root discovers platform Applications and the `box1-workloads-dev`
parent. The development parent discovers service Applications in the new
repository. Each service Application reads `workloads/<service>` there.
Platform-owned Tasks and Developer Hub runtime code stay in `box1-gitops`.
Source repositories retain their original `deploy/` directories. These are
scaffold/source manifests; development image promotion edits the environment
repository rather than rewriting source manifests.

## Ordered cutover

1. Refresh platform source and verify there are no active onboarding or release
   runs. Capture workload Deployment UIDs, specs, Pod UIDs, and image digests.
2. Populate the development repository with all five workload directories,
   their Applications, and validation PipelineRuns. Preserve workload paths,
   application names, namespaces, image digests, and runtime configuration.
3. Verify anonymous HTTPS access to the public development repository, matching
   the platform repository visibility. No Argo CD repository credential is needed.
4. Publish the platform change registering the dev PAC repository, redirecting
   promotion and onboarding, and adding the development parent. Remove the five
   old child Application files and workload directories from the platform tree.
   Keep application pruning disabled during the ownership transfer. Do not
   delete any live Applications or attach deletion finalizers.
5. Sync `pipelines-ci` and `developer-hub` manually, then reconcile both parents.
6. Verify all five Applications are Synced/Healthy from the dev repository;
   compare Deployment specs/UIDs and Pod UIDs with the baseline.
7. Exercise a dev-repository PR: verify both required checks from the expected
   App, merge it, and observe Argo CD reconciliation. Verify new onboarding
   and promotion targets, source manifest retention, and credential scope.

## Rollback

Restore the pre-cutover platform Application definitions and workloads from
`f682e73`, restore platform promotion/onboarding targets, and sync the platform
Applications. Keep the development parent inactive while ownership transfers
back. Reuse existing Application identities; do not delete Applications or
runtime namespaces. A repository rollback must preserve the currently approved
image digest, or explicitly record an intentional release rollback.

## Stage and production

These environments are future work. Use separate repositories and parent
Applications, environment namespaces, constrained credentials, and review gates.
Promote the same tested digest with source/build provenance and the upstream
environment commit; validate and approve each environment PR before merging.
