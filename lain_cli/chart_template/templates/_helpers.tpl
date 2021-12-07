{{/* vim: set filetype=mustache: */}}

{{- define "chart.image" -}}
{{ $reg := default .Values.registry .Values.internalRegistry }}
{{- printf "%s/%s:%s" $reg .Values.appname .Values.imageTag}}
{{- end -}}

{{- define "chart.registry" -}}
{{ default .Values.registry .Values.internalRegistry }}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}

{{/*
Common labels
*/}}
{{- define "chart.labels" -}}
helm.sh/chart: {{ .Release.Name }}
{{ include "chart.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.labels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "chart.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.appname }}
{{- end -}}

{{- define "deployment.apiVersion" -}}
{{- if semverCompare "<1.14-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "extensions/v1beta1" -}}
{{- else if semverCompare ">=1.14-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "apps/v1" -}}
{{- end -}}
{{- end -}}

{{- define "statefulSet.apiVersion" -}}
{{- if semverCompare "<1.14-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "apps/v1beta2" -}}
{{- else -}}
{{- print "apps/v1" -}}
{{- end -}}
{{- end -}}

{{- define "cronjob.apiVersion" -}}
{{- if semverCompare "< 1.8-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "batch/v2alpha1" }}
{{- else if semverCompare ">=1.8-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "batch/v1beta1" }}
{{- end -}}
{{- end -}}

{{- define "ingress.apiVersion" -}}
{{- if semverCompare "<1.14-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "extensions/v1beta1" -}}
{{- else if semverCompare ">=1.19-0" .Capabilities.KubeVersion.GitVersion -}}
{{- print "networking.k8s.io/v1" -}}
{{- else -}}
{{- print "networking.k8s.io/v1beta1" -}}
{{- end -}}
{{- end -}}

{{- define "hostAliases" -}}
hostAliases:
{{- with $.Values.clusterHostAliases }}
{{ toYaml $.Values.clusterHostAliases }}
{{- end }}
{{- with $.Values.hostAliases }}
{{ toYaml $.Values.hostAliases }}
{{- end }}
{{- end -}}

{{- define "clusterEnv" -}}
- name: LAIN_CLUSTER
  value: {{ default "UNKNOWN" $.Values.cluster }}
- name: K8S_NAMESPACE
  value: {{ default "default" $.Values.namespace }}
- name: IMAGE_TAG
  value: {{ default "UNKNOWN" $.Values.imageTag }}
{{- end -}}

{{- define "appEnv" -}}
{{- if hasKey $ "env" }}
{{- range $index, $element := $.env }}
- name: {{ $index | quote }}
  value: {{ $element | quote }}
{{- end -}}
{{- end -}}
{{- end -}}
