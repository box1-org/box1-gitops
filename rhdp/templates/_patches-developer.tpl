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
