{{/*
Shared values. Everything here must stay Helm 3 compatible: Argo CD renders
this chart with its bundled Helm 3.
*/}}

{{- define "box1.domain" -}}
{{- required "deployer.domain is injected by ocp4_workload_field_content and is required" .Values.deployer.domain -}}
{{- end -}}

{{- define "box1.apiUrl" -}}
{{- .Values.deployer.apiUrl | default (printf "https://api.%s:6443" (trimPrefix "apps." (include "box1.domain" .))) -}}
{{- end -}}

{{- define "box1.keycloakBaseUrl" -}}
https://{{ .Values.keycloak.hostPrefix }}.{{ include "box1.domain" . }}
{{- end -}}

{{- define "box1.issuer" -}}
{{ include "box1.keycloakBaseUrl" . }}/realms/{{ .Values.keycloak.realm }}
{{- end -}}

{{- define "box1.registryHost" -}}
{{- .Values.registry.host | default (printf "default-route-openshift-image-registry.%s" (include "box1.domain" .)) -}}
{{- end -}}

{{- define "box1.s3PublicEndpoint" -}}
{{- .Values.storage.s3PublicEndpoint | default (printf "https://s3-openshift-storage.%s" (include "box1.domain" .)) -}}
{{- end -}}

{{/* https://<host>/<org>/<repo> for a git.repos key. Args: dict root repo */}}
{{- define "box1.gitUrl" -}}
{{- $g := .root.Values.git -}}
https://{{ $g.host }}/{{ $g.org }}/{{ index $g.repos .repo }}
{{- end -}}

{{/* gitops.repoURL without scheme, host, or .git: <org>/<repo> */}}
{{- define "box1.gitopsSlug" -}}
{{- $u := .Values.gitops.repoURL | trimSuffix "/" | trimSuffix ".git" -}}
{{- $parts := splitList "/" $u -}}
{{- $n := len $parts -}}
{{- if lt $n 2 -}}{{- fail "gitops.repoURL must look like https://<host>/<org>/<repo>" -}}{{- end -}}
{{- printf "%s/%s" (index $parts (sub $n 2)) (index $parts (sub $n 1)) -}}
{{- end -}}

{{- define "box1.gitopsUrl" -}}
{{- .Values.gitops.repoURL | trimSuffix "/" | trimSuffix ".git" -}}
{{- end -}}

{{/* Truthy check of a dotted value path. Args: dict root path. Prints "true" or "". */}}
{{- define "box1.valueSet" -}}
{{- $v := .root.Values -}}
{{- range splitList "." .path -}}
{{- if kindIs "map" $v -}}{{- $v = index $v . -}}{{- else -}}{{- $v = "" -}}{{- end -}}
{{- end -}}
{{- if $v -}}true{{- end -}}
{{- end -}}

{{- define "box1.litemaasEnabled" -}}
{{- if and .Values.litemaas.enabled .Values.litemaas.apiUrl -}}true{{- end -}}
{{- end -}}

{{/* "true" when any of the component's profiles is on. Args: dict root c */}}
{{- define "box1.profileOn" -}}
{{- $on := false -}}
{{- range .c.profiles -}}
{{- if index $.root.Values.profiles . -}}{{- $on = true -}}{{- end -}}
{{- end -}}
{{- if $on -}}true{{- end -}}
{{- end -}}

{{/*
Why a component whose profile is on is not rendered; "" renders it.
Args: dict root c
*/}}
{{- define "box1.skipReason" -}}
{{- $root := .root -}}
{{- $c := .c -}}
{{- $r := default dict $c.requires -}}
{{- $reasons := list -}}
{{- if eq (toString $c.enabled) "false" -}}{{- $reasons = append $reasons "disabled (enabled: false)" -}}{{- end -}}
{{- range $r.profiles -}}
{{- if not (index $root.Values.profiles .) -}}{{- $reasons = append $reasons (printf "profile %s is off" .) -}}{{- end -}}
{{- end -}}
{{- if and $r.objectStore (ne $root.Values.storage.objectStore "odf") -}}{{- $reasons = append $reasons "needs storage.objectStore: odf" -}}{{- end -}}
{{- if and $r.rwoClass (not $root.Values.storage.rwoClass) -}}{{- $reasons = append $reasons "needs storage.rwoClass" -}}{{- end -}}
{{- if and $r.litemaas (not (include "box1.litemaasEnabled" $root)) -}}{{- $reasons = append $reasons "needs LiteMaaS (litemaas.enabled and apiUrl)" -}}{{- end -}}
{{- range $r.unset -}}
{{- if include "box1.valueSet" (dict "root" $root "path" .) -}}{{- $reasons = append $reasons (printf "%s is set" .) -}}{{- end -}}
{{- end -}}
{{- range $r.values -}}
{{- if not (include "box1.valueSet" (dict "root" $root "path" .)) -}}{{- $reasons = append $reasons (printf "needs %s" .) -}}{{- end -}}
{{- end -}}
{{- join "; " $reasons -}}
{{- end -}}

{{/* Values written into each overlay's box1-platform-settings ConfigMap. */}}
{{- define "box1.settings" -}}
{{- $d := include "box1.domain" . -}}
BOX1_APPS_DOMAIN: {{ $d | quote }}
BOX1_API_URL: {{ include "box1.apiUrl" . | quote }}
BOX1_CONSOLE_URL: {{ printf "https://console-openshift-console.%s" $d | quote }}
BOX1_OIDC_ISSUER: {{ include "box1.issuer" . | quote }}
BOX1_KEYCLOAK_BASE_URL: {{ include "box1.keycloakBaseUrl" . | quote }}
BOX1_KEYCLOAK_REALM: {{ .Values.keycloak.realm | quote }}
BOX1_GIT_HOST: {{ .Values.git.host | quote }}
BOX1_GIT_ORG: {{ .Values.git.org | quote }}
BOX1_GITOPS_REPO_URL: {{ include "box1.gitopsUrl" . | quote }}
BOX1_WORKLOADS_REPO_URL: {{ include "box1.gitUrl" (dict "root" . "repo" "workloadsDev") | quote }}
BOX1_TEMPLATES_REPO_URL: {{ include "box1.gitUrl" (dict "root" . "repo" "templates") | quote }}
BOX1_DOCS_REPO_URL: {{ include "box1.gitUrl" (dict "root" . "repo" "docs") | quote }}
BOX1_REGISTRY_HOST: {{ include "box1.registryHost" . | quote }}
BOX1_TPA_URL: {{ printf "https://tpa.%s" $d | quote }}
BOX1_ACS_URL: {{ printf "https://acs.%s" $d | quote }}
BOX1_ARGOCD_URL: {{ printf "https://openshift-gitops-server-openshift-gitops.%s" $d | quote }}
BOX1_OIDC_METADATA_URL: {{ printf "%s/.well-known/openid-configuration" (include "box1.issuer" .) | quote }}
BOX1_TEMPLATES_CATALOG_URL: {{ printf "%s/blob/main/catalog-info.yaml" (include "box1.gitUrl" (dict "root" . "repo" "templates")) | quote }}
BOX1_DEVSPACES_URL: {{ printf "https://devspaces.%s" $d | quote }}
BOX1_KIALI_URL: {{ printf "https://kiali-istio-system.%s" $d | quote }}
BOX1_OPERATIONS_CONSOLE_URL: {{ printf "https://operations-console-dev.%s" $d | quote }}
{{- $on := list -}}
{{- range $p, $v := .Values.profiles -}}{{- if $v -}}{{- $on = append $on $p -}}{{- end -}}{{- end }}
BOX1_PROFILES: {{ join "," $on | quote }}
{{- $opt := list -}}
{{- range $k, $v := .Values.ci.optionalRepositories -}}{{- if $v -}}{{- $opt = append $opt $k -}}{{- end -}}{{- end }}
BOX1_CI_OPTIONAL: {{ join "," $opt | quote }}
BOX1_LITEMAAS: {{ ternary "true" "false" (eq (include "box1.litemaasEnabled" .) "true") | quote }}
BOX1_ONBOARDING_PLUGIN_PACKAGE: {{ .Values.developerHub.onboardingPluginPackage | quote }}
BOX1_ADMIN_USERS: {{ join "," .Values.keycloak.adminUsers | quote }}
BOX1_SYSTEM_NAMESPACE: {{ .Values.system.namespace | quote }}
BOX1_INPUTS_SECRET: {{ .Values.system.inputsSecret | quote }}
{{- end -}}

{{/*
Patch builders. Each returns one kustomize patch entry as YAML:
  target: {kind, name}
  patch: <string>
*/}}

{{/* Args: dict root key */}}
{{- define "box1.patch.subscription" -}}
{{- $s := index .root.Values.operators.subscriptions .key -}}
{{- if not $s -}}{{- fail (printf "operators.subscriptions.%s is not defined" .key) -}}{{- end -}}
{{- $d := .root.Values.operators.defaults -}}
{{- $spec := dict "channel" $s.channel "source" ($s.source | default $d.source) "sourceNamespace" ($s.sourceNamespace | default $d.sourceNamespace) "installPlanApproval" ($s.installPlanApproval | default $d.installPlanApproval) "startingCSV" ($s.startingCSV | default nil) -}}
{{- $p := dict "apiVersion" "operators.coreos.com/v1alpha1" "kind" "Subscription" "metadata" (dict "name" $s.name "namespace" $s.namespace) "spec" $spec -}}
target:
  kind: Subscription
  name: {{ $s.name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict root name prefix */}}
{{- define "box1.patch.routeHost" -}}
{{- $p := dict "apiVersion" "route.openshift.io/v1" "kind" "Route" "metadata" (dict "name" .name) "spec" (dict "host" (printf "%s.%s" .prefix (include "box1.domain" .root))) -}}
target:
  kind: Route
  name: {{ .name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict root name. rwoClass "" removes storageClassName (default class). */}}
{{- define "box1.patch.pvc" -}}
{{- $p := dict "apiVersion" "v1" "kind" "PersistentVolumeClaim" "metadata" (dict "name" .name) "spec" (dict "storageClassName" (.root.Values.storage.rwoClass | default nil)) -}}
target:
  kind: PersistentVolumeClaim
  name: {{ .name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict root name */}}
{{- define "box1.patch.obc" -}}
{{- $p := dict "apiVersion" "objectbucket.io/v1alpha1" "kind" "ObjectBucketClaim" "metadata" (dict "name" .name) "spec" (dict "storageClassName" .root.Values.storage.objectBucketClass) -}}
target:
  kind: ObjectBucketClaim
  name: {{ .name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict root name extra - settings data (plus extra overrides) into a ConfigMap (default box1-platform-settings) */}}
{{- define "box1.patch.settings" -}}
{{- $name := .name | default "box1-platform-settings" -}}
{{- $data := merge (default dict .extra) (include "box1.settings" .root | fromYaml) -}}
{{- $p := dict "apiVersion" "v1" "kind" "ConfigMap" "metadata" (dict "name" $name) "data" $data -}}
target:
  kind: ConfigMap
  name: {{ $name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict kind name [group version] - deletes a resource from the build */}}
{{- define "box1.patch.delete" -}}
{{- $p := dict "$patch" "delete" "apiVersion" (.apiVersion | default "v1") "kind" .kind "metadata" (dict "name" .name) -}}
target:
  kind: {{ .kind }}
  name: {{ .name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict kind name ops (list of JSON6902 operations) */}}
{{- define "box1.patch.json" -}}
target:
  kind: {{ .kind }}
  name: {{ .name }}
patch: {{ toYaml .ops | quote }}
{{- end -}}

{{/* Args: dict root kind name apiVersion spec - strategic-merge patch of spec (CRs: JSON merge semantics) */}}
{{- define "box1.patch.spec" -}}
{{- $p := dict "apiVersion" .apiVersion "kind" .kind "metadata" (dict "name" .name) "spec" .spec -}}
target:
  kind: {{ .kind }}
  name: {{ .name }}
patch: {{ toYaml $p | quote }}
{{- end -}}

{{/* Args: dict kind name body - strategic-merge patch with an arbitrary body (kind/metadata added) */}}
{{- define "box1.patch.object" -}}
{{- $p := merge (dict "kind" .kind "metadata" (dict "name" .name)) .body -}}
target:
  kind: {{ .kind }}
  name: {{ .name }}
patch: {{ toYaml $p | quote }}
{{- end -}}
