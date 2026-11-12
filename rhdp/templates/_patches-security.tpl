{{/* Component-specific kustomize patches for the security profile. Args: dict root c */}}

{{- define "box1.k.acs" -}}
{{- $v := .root.Values -}}
{{- $class := $v.storage.rwoClass | default nil -}}
{{- $pvc := dict "persistentVolumeClaim" (dict "storageClassName" $class) -}}
{{- $central := dict
      "exposure" (dict "route" (dict "host" (printf "acs.%s" (include "box1.domain" .root))))
      "persistence" $pvc
      "db" (dict "persistence" $pvc) -}}
{{- $spec := dict "central" $central "scannerV4" (dict "db" (dict "persistence" $pvc)) -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "platform.stackrox.io/v1alpha1" "kind" "Central" "name" "stackrox-central-services" "spec" $spec) | nindent 4 | trim }}
  - {{ include "box1.patch.spec" (dict "apiVersion" "platform.stackrox.io/v1alpha1" "kind" "SecuredCluster" "name" "stackrox-secured-cluster-services" "spec" (dict "clusterName" $v.security.acs.clusterName)) | nindent 4 | trim }}
{{- end -}}

{{- define "box1.k.rhtpaOperator" -}}
patches:
{{- if not .root.Values.security.rhtpa.customCatalog }}
  {{- /* The homelab pins an OCP 4.22 index; use the cluster's redhat-operators. */}}
  - {{ include "box1.patch.delete" (dict "apiVersion" "operators.coreos.com/v1alpha1" "kind" "CatalogSource" "name" "rhtpa-redhat-current") | nindent 4 | trim }}
{{- else }} []
{{- end }}
{{- end -}}

{{- define "box1.k.rhtpaPrerequisites" -}}
{{- $v := .root.Values -}}
{{- $d := include "box1.domain" .root -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "objectbucket.io/v1alpha1" "kind" "ObjectBucketClaim" "name" "rhtpa-documents" "spec" (dict "generateBucketName" nil "bucketName" $v.security.rhtpa.bucketName)) | nindent 4 | trim }}
{{- if eq $v.security.rhtpa.tls "certManager" }}
  - {{ include "box1.patch.spec" (dict "apiVersion" "cert-manager.io/v1" "kind" "Certificate" "name" "rhtpa-tls" "spec" (dict "dnsNames" (list (printf "tpa.%s" $d)) "issuerRef" (dict "name" $v.security.rhtpa.clusterIssuer "kind" "ClusterIssuer"))) | nindent 4 | trim }}
{{- else }}
  - {{ include "box1.patch.delete" (dict "apiVersion" "cert-manager.io/v1" "kind" "Certificate" "name" "rhtpa-tls") | nindent 4 | trim }}
{{- end }}
{{- end -}}

{{/* rhtpa-auth with the RHDP issuer. Must equal platform/trusted-profile-analyzer/instance/auth.yaml apart from issuerUrl (checked by rhdp/tests). */}}
{{- define "box1.rhtpaAuth" -}}
{{- $issuer := include "box1.issuer" . -}}
{{- $front := dict "clientId" "rhtpa-frontend" "issuerUrl" $issuer
      "additionalPermissions" (list "read.advisory" "read.importer" "read.metadata" "read.sbom" "read.sbomGroup" "read.weakness" "read.systemInformation")
      "groupSelector" "$['realm_access']['roles'][*]"
      "groupMappings" (dict "rhtpa-admin" (list "create.advisory" "create.importer" "create.metadata" "create.sbom" "create.sbomGroup" "create.weakness" "upload.dataset" "update.advisory" "update.importer" "update.metadata" "update.sbom" "update.sbomGroup" "update.weakness" "delete.advisory" "delete.importer" "delete.metadata" "delete.sbom" "delete.sbomGroup" "delete.vulnerability" "delete.weakness")) -}}
{{- $ci := dict "clientId" "rhtpa-ci" "issuerUrl" $issuer "additionalPermissions" (list "create.sbom" "read.sbom" "read.metadata") -}}
{{- dict "authentication" (dict "clients" (list $front $ci)) | toJson -}}
{{- end -}}

{{- define "box1.k.rhtpa" -}}
{{- $v := .root.Values -}}
{{- $d := include "box1.domain" .root -}}
{{- $host := printf "tpa.%s" $d -}}
{{- $tls := dict "hosts" (list $host) -}}
{{- if eq $v.security.rhtpa.tls "certManager" }}{{- $_ := set $tls "secretName" "rhtpa-tls" -}}{{- end -}}
{{- $spec := dict
      "appDomain" (printf ".%s" $d)
      "storage" (dict "bucket" $v.security.rhtpa.bucketName "region" (include "box1.s3PublicEndpoint" .root))
      "oidc" (dict "issuerUrl" (include "box1.issuer" .root))
      "ingress" (dict "tls" (list $tls))
      "modules" (dict "server" (dict "ingress" (dict "hosts" (list $host)))) -}}
patches:
  - {{ include "box1.patch.spec" (dict "apiVersion" "rhtpa.io/v1" "kind" "TrustedProfileAnalyzer" "name" "rhtpa" "spec" $spec) | nindent 4 | trim }}
  - {{ include "box1.patch.object" (dict "kind" "ConfigMap" "name" "rhtpa-auth" "body" (dict "apiVersion" "v1" "data" (dict "auth.yaml" (include "box1.rhtpaAuth" .root)))) | nindent 4 | trim }}
{{- end -}}
