{{/* Component-specific kustomize patches for the operate profile. Args: dict root c */}}

{{- define "box1.k.kiali" -}}
{{- $d := include "box1.domain" .root -}}
{{- $spec := dict "external_services" (dict "tracing" (dict "external_url" (printf "https://tempo-box1-jaegerui-box1-observability.%s/api/traces/v1/dev/search" $d))) -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "kiali.io/v1alpha1" "kind" "Kiali" "name" "kiali" "spec" $spec) | nindent 4 | trim }}
{{- end -}}

{{- define "box1.k.observabilityLogging" -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "loki.grafana.com/v1" "kind" "LokiStack" "name" "logging-loki" "spec" (dict "storageClassName" .root.Values.storage.rwoClass)) | nindent 4 | trim }}
{{- end -}}
