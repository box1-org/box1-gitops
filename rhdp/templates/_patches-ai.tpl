{{/* Component-specific kustomize patches for the ai profile. Args: dict root c */}}

{{- define "box1.k.lightspeed" -}}
{{- $v := .root.Values -}}
{{- $provider := dict "name" "litemaas" "type" "openai" "url" $v.litemaas.apiUrl
      "credentialsSecretRef" (dict "name" "lightspeed-litemaas-credentials")
      "models" (list (dict "name" $v.litemaas.model "contextWindowSize" $v.ai.lightspeed.contextWindowSize "parameters" (dict "maxTokensForResponse" 4096))) -}}
{{- $spec := dict
      "llm" (dict "providers" (list $provider))
      "ols" (dict "defaultProvider" "litemaas" "defaultModel" $v.litemaas.model
                  "deployment" (dict "rhokp" (dict "resources" (dict "requests" (dict "ephemeral-storage" $v.ai.lightspeed.rhokpEphemeralStorage))))) -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "ols.openshift.io/v1alpha1" "kind" "OLSConfig" "name" "cluster" "spec" $spec) | nindent 4 | trim }}
{{- end -}}

{{- define "box1.k.langfuse" -}}
{{- $d := include "box1.domain" .root -}}
{{- $web := dict "name" "web" "env" (list
      (dict "name" "LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT" "value" (include "box1.s3PublicEndpoint" .root))
      (dict "name" "AUTH_KEYCLOAK_ISSUER" "value" (include "box1.issuer" .root))) -}}
patches:
  - {{ include "box1.patch.object" (dict "kind" "ConfigMap" "name" "langfuse-config" "body" (dict "apiVersion" "v1" "data" (dict "NEXTAUTH_URL" (printf "https://langfuse.%s" $d)))) | nindent 4 | trim }}
  - {{ include "box1.patch.object" (dict "kind" "Deployment" "name" "langfuse-web" "body" (dict "apiVersion" "apps/v1" "spec" (dict "template" (dict "spec" (dict "containers" (list $web)))))) | nindent 4 | trim }}
{{- end -}}
