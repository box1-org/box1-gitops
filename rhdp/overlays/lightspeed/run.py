"""OpenShift Lightspeed LiteMaaS credentials. Values are never printed."""
import os

import k8s

key = k8s.inputs().get("LITEMAAS_API_KEY") or (
    k8s.get_secret(os.environ.get("BOX1_SYSTEM_NAMESPACE", "box1-rhdp-system"), "box1-rhdp-litemaas") or {}).get("apiKey")
if key:
    k8s.apply_secret(k8s.NAMESPACE, "lightspeed-litemaas-credentials", {"apitoken": key.strip()})
else:
    k8s.missing("lightspeed-litemaas-credentials: no LITEMAAS_API_KEY input or box1-rhdp-litemaas Secret")
k8s.finish()
