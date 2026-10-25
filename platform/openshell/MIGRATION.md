# Proposed Helm-to-Argo ownership migration

Status: documented for review only. Storing an Application and values in Git
does not authorize activating it. Helm remains the live reconciler today.
Do not add the staged Application to `applications/` or apply/sync it as part
of the repository organization change.

## Resource ownership before migration

| Resource | Current owner | Desired treatment |
| --- | --- | --- |
| Gateway StatefulSet, Services, RBAC, ConfigMap, Route | Helm release openshell | Adopt in place after reviewed diff |
| Certificate and Issuer resources | Helm; issuance by cert-manager | Adopt definitions; preserve current Secret contents |
| Credential encryption key | Existing live Secret | External existing-Secret reference; preserve exact bytes |
| Gateway JWT signing keys | Existing live Secret | Preserve signing identity; audit chart certgen hook |
| Agent Sandbox CRDs/controller | Existing installation | Remain outside this Application; chart skipCrds=true |
| Sandbox resources and supervisor/workload pods | OpenShell driver/controller | Remain outside direct Argo desired resources |
| Gateway data PVC and workspace PVCs | Existing StatefulSet/Sandbox resources | Preserve PVCs, PV bindings and stored data |
| Keycloak operator/database/realm/client | Existing identity Applications | No ownership transfer |

## Proposed sequence

1. Establish an authorized maintenance window and stop new Helm operations.
   Capture release history, actual chart digest, user/computed values, hooks,
   resource UIDs, PVC/PV bindings and live manifests outside Git. Record
   fingerprints of gateway signing and credential encryption keys. Take verified
   LVM snapshots of the gateway PVC and both workspace PVCs. Existing presecure
   snapshots are named `openshell-presecure-r3-{data,coder,coder-v2}`; verify their
   state rather than assuming they are a current backup.
2. Resolve the chart's offline-lookup behavior before activating Argo.
   Argo renders Helm templates rather than running a Helm upgrade and cannot
   rely on the existing release's live Secret lookup. The current chart can
   generate a random credential encryption key during offline rendering.
   Prepare and review an adoption-specific values change selecting the existing
   `server.credentialStorage.existingSecret` and
   `server.sandboxJwt.signingSecretName`. Ensure the old Secret resource cannot
   be pruned when it disappears from the chart render. Keep those changes
   separate from today's exact-live `values.yaml` snapshot.
3. Audit certgen hook resources and their Argo hook translation, including
   ServiceAccounts, RBAC, JWT-only job behavior and deletion policies. Preserve
   existing JWT data and cert-manager CA/leaf Secret contents. Check internal
   server and client `ca.crt` equality. The previous TLS rollout required manually
   renewing an adopted legacy client certificate under the new CA; repeating
   certificate adoption must not reintroduce that mismatch.
4. Render with the actual Argo/Helm versions, chart digest, releaseName
   `openshell`, namespace `openshell` and served Agent Sandbox APIs. Compare every
   rendered resource against live state. Review StatefulSet immutable fields,
   volumeClaimTemplates, service/selector labels, security overrides, image
   digests and pull Secrets. No random key, PVC replacement, CRD adoption or
   unrelated resource should be in the adoption diff. Server-side dry run alone
   does not prove that encrypted credentials or supervisor sessions survive.
5. Review the proposed ownership diff and rollback procedure, then obtain explicit
   authorization to activate the Application. Keep automated sync, pruning,
   cascading deletion and namespace creation disabled for initial adoption.
   Register only this Application; do not install a new root app as a shortcut.
   Account for Argo tracking labels and Helm ownership annotations explicitly.
6. Perform one controlled adoption sync. Leave the original Helm release history
   available, but do not continue Helm upgrades while Argo is the active owner.
   Do not uninstall the Helm release: that would delete live resources rather
   than transfer ownership. Gateway pod changes can interrupt sessions; do not
   assume the Helm-to-Argo adoption is a zero-restart operation.
7. Verify exact-hostname HTTPS, issuer discovery, authenticated CLI access,
   rejection of anonymous requests, all certificates Ready, identical signing
   and encryption keys, unchanged Sandbox/PVC identities, and harmless execution
   in both box1-coder sandboxes. If pod recreation is required, use the supported
   Sandbox suspend and OpenShell start lifecycle with the existing resources;
   never delete the Sandbox resources or workspace PVCs.
8. Only after successful observation should a separately reviewed change enable
   automated reconciliation or move the Application into the app-of-apps set.

## Rollback design to review before activation

Pause Argo reconciliation before any Helm rollback to avoid two controllers
writing the same resources. Compare against the pre-adoption Helm revision and
preserved key fingerprints. A Helm rollback cannot reverse lost or replaced
key material. Decide in advance how to restore configuration without deleting
Sandbox resources or PVCs, and when a snapshot restore would require a separate
recovery operation. Do not automatically roll back to revision 3: it enables
plaintext transport and anonymous access. Revision 4 is the secure baseline.

This plan is preparatory; completing it is a separate migration task.
