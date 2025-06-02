{{- define "hpaversion" -}}
{{- if or (eq .Values.datacenter "atl") (eq .Values.datacenter "tor") (eq .Values.datacenter "plas1") (eq .Values.datacenter "dlas1") }}v2beta2{{ else }}v2{{ end }}
{{- end -}}
