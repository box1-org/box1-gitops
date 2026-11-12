{{/* Component-specific kustomize patches for the developer profile. Args: dict root c */}}

{{- define "box1.k.pipelinesConfig" -}}
{{- $console := printf "https://console-openshift-console.%s" (include "box1.domain" .root) -}}
{{- $settings := dict
      "custom-console-url" $console
      "custom-console-url-namespace" (printf "%s/pipelines/ns/{{ namespace }}" $console)
      "custom-console-url-pr-details" (printf "%s/k8s/ns/{{ namespace }}/tekton.dev~v1~PipelineRun/{{ pr }}" $console)
      "custom-console-url-pr-tasklog" (printf "%s/k8s/ns/{{ namespace }}/tekton.dev~v1~PipelineRun/{{ pr }}/logs/{{ task }}" $console) -}}
{{- $spec := dict "platforms" (dict "openshift" (dict "pipelinesAsCode" (dict "settings" $settings))) -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "operator.tekton.dev/v1alpha1" "kind" "TektonConfig" "name" "config" "spec" $spec) | nindent 4 | trim }}
{{- end -}}

{{- define "box1.k.pipelinesCi" -}}
{{- $root := .root -}}
{{- $v := $root.Values -}}
{{- $org := $v.git.org -}}
{{- $gitops := include "box1.gitopsSlug" $root -}}
{{- $workloads := printf "%s/%s" $org $v.git.repos.workloadsDev -}}
{{- $prefix := printf "https://%s/" $v.git.host -}}
{{- /* Repository CR -> url, token scope (empty: no scope setting) */ -}}
{{- $repos := list
      (dict "name" "box1-gitops" "url" (include "box1.gitopsUrl" $root) "scope" (list $gitops))
      (dict "name" "box1-workloads-dev" "url" (print $prefix $workloads) "scope" (list $workloads))
      (dict "name" "quarkus-reference" "url" (printf "%s%s/%s" $prefix $org $v.git.repos.quarkusReference) "scope" (list $workloads))
      (dict "name" "box1-templates" "url" (printf "%s%s/%s" $prefix $org $v.git.repos.templates) "scope" (list $gitops))
      (dict "name" "box1-build" "url" (printf "%s%s/%s" $prefix $org $v.git.repos.build) "scope" list) -}}
{{- if $v.ci.optionalRepositories.devspaces -}}
{{- $repos = append $repos (dict "name" "box1-devspaces" "url" (printf "%s%s/%s" $prefix $org $v.git.repos.devspaces) "scope" list) -}}
{{- end -}}
{{- if $v.ci.optionalRepositories.erpSimulator -}}
{{- $repos = append $repos (dict "name" "box1-ops-erp-simulator" "url" (printf "%s%s/%s" $prefix $org $v.git.repos.erpSimulator) "scope" (list $workloads (printf "%s/%s" $org $v.git.repos.legacyErp))) -}}
{{- end }}
patches:
{{- range $repos }}
  {{- $ops := list (dict "op" "replace" "path" "/spec/url" "value" .url) }}
  {{- if .scope }}
  {{- $ops = append $ops (dict "op" "replace" "path" "/spec/settings/github_app_token_scope_repos" "value" .scope) }}
  {{- end }}
  - {{ include "box1.patch.json" (dict "kind" "Repository" "name" .name "ops" $ops) | nindent 4 | trim }}
{{- end }}
{{- if not $v.ci.optionalRepositories.devspaces }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "pipelinesascode.tekton.dev/v1alpha1" "kind" "Repository" "name" "box1-devspaces") | nindent 4 | trim }}
{{- end }}
{{- if not $v.ci.optionalRepositories.erpSimulator }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "pipelinesascode.tekton.dev/v1alpha1" "kind" "Repository" "name" "box1-ops-erp-simulator") | nindent 4 | trim }}
{{- end }}
{{- if not $v.ci.optionalRepositories.bootc }}
  {{- /* Privileged SCC is only for bootc image builds. */}}
  - {{ include "box1.patch.delete" (dict "apiVersion" "rbac.authorization.k8s.io/v1" "kind" "RoleBinding" "name" "ci-bootc-privileged-scc") | nindent 4 | trim }}
{{- end }}
{{- if not $v.ci.optionalRepositories.siteImages }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "image.openshift.io/v1" "kind" "ImageStream" "name" "site-amq-broker") | nindent 4 | trim }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "image.openshift.io/v1" "kind" "ImageStream" "name" "site-postgresql") | nindent 4 | trim }}
{{- end }}
{{- if not $v.profiles.rhbk }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "rbac.authorization.k8s.io/v1" "kind" "Role" "name" "box1-ci-credentials-keycloak") | nindent 4 | trim }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "rbac.authorization.k8s.io/v1" "kind" "RoleBinding" "name" "box1-ci-credentials-keycloak") | nindent 4 | trim }}
{{- end }}
{{- if not $v.profiles.security }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "rbac.authorization.k8s.io/v1" "kind" "Role" "name" "box1-ci-credentials-stackrox") | nindent 4 | trim }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "rbac.authorization.k8s.io/v1" "kind" "RoleBinding" "name" "box1-ci-credentials-stackrox") | nindent 4 | trim }}
{{- end }}
{{- if $v.ci.builderImage }}
images:
  - {{ printf "image-registry.openshift-image-registry.svc:5000/box1-build/box1-builder=%s" $v.ci.builderImage | quote }}
{{- end }}
{{- end -}}

{{- define "box1.k.developerHub" -}}
{{- $root := .root -}}
{{- $v := $root.Values -}}
{{- $d := include "box1.domain" $root -}}
{{- $lightspeed := ternary (eq (include "box1.litemaasEnabled" $root) "true") (eq (toString $v.developerHub.lightspeed) "true") (eq (toString $v.developerHub.lightspeed) "auto") -}}
{{- $base := "/spec/deployment/patch/spec/template/spec" -}}
patches:
  {{- /* In-cluster API: the RHDP API certificate is not publicly trusted; the
         platform-trust bundle carries the service-account CA. */}}
  - {{ include "box1.patch.settings" (dict "root" $root "name" "developer-hub-platform-env" "extra" (dict "BOX1_API_URL" "https://kubernetes.default.svc")) | nindent 4 | trim }}
  - {{ include "box1.patch.spec" (dict "apiVersion" "rhdh.redhat.com/v1alpha5" "kind" "Backstage" "name" "developer-hub" "spec" (dict "application" (dict "route" (dict "host" (printf "developer-hub.%s" $d))))) | nindent 4 | trim }}
  - {{ include "box1.patch.pvc" (dict "root" $root "name" "dynamic-plugins-root") | nindent 4 | trim }}
  {{- if $lightspeed }}
  {{- $env := dict "VLLM_URL" $v.litemaas.apiUrl "VLLM_MODEL" $v.litemaas.model "VLLM_TLS_VERIFY" "true" "VLLM_API_KEY" nil }}
  - {{ include "box1.patch.object" (dict "kind" "ConfigMap" "name" "developer-hub-llama-stack-env" "body" (dict "apiVersion" "v1" "data" $env)) | nindent 4 | trim }}
  - {{ include "box1.patch.json" (dict "kind" "Backstage" "name" "developer-hub" "ops" (list
        (dict "op" "test" "path" (printf "%s/containers/1/name" $base) "value" "llama-stack")
        (dict "op" "add" "path" (printf "%s/containers/1/envFrom/-" $base) "value" (dict "secretRef" (dict "name" "developer-hub-lightspeed-litemaas"))))) | nindent 4 | trim }}
  {{- else }}
  {{- /* No model endpoint: drop the Lightspeed sidecars and the RAG init container. */}}
  - {{ include "box1.patch.json" (dict "kind" "Backstage" "name" "developer-hub" "ops" (list
        (dict "op" "test" "path" (printf "%s/containers/2/name" $base) "value" "lightspeed-core")
        (dict "op" "remove" "path" (printf "%s/containers/2" $base))
        (dict "op" "test" "path" (printf "%s/containers/1/name" $base) "value" "llama-stack")
        (dict "op" "remove" "path" (printf "%s/containers/1" $base))
        (dict "op" "test" "path" (printf "%s/initContainers/1/name" $base) "value" "init-rag-data")
        (dict "op" "remove" "path" (printf "%s/initContainers/1" $base)))) | nindent 4 | trim }}
  - {{ include "box1.patch.delete" (dict "kind" "ConfigMap" "name" "developer-hub-llama-stack-env") | nindent 4 | trim }}
  {{- end }}
{{- end -}}

