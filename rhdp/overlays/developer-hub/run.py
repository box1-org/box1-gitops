"""Developer Hub credentials on RHDP. Values are never printed."""
import base64
import json
import os
import ssl
import urllib.request
import uuid
from datetime import datetime, timezone

import k8s

ns = k8s.NAMESPACE
inputs = k8s.inputs()
profiles = set(filter(None, os.environ.get("BOX1_PROFILES", "").split(",")))

# Trust: router CA for in-cluster calls to routes, plus the service-account CA
# so the Kubernetes plugin can verify https://kubernetes.default.svc.
ingress = (k8s.get_configmap("openshift-config-managed", "default-ingress-cert") or {}).get("ca-bundle.crt", "")
kube = (k8s.get_configmap(ns, "kube-root-ca.crt") or {}).get("ca.crt", "")
if ingress and kube:
    k8s.apply_configmap(ns, "developer-hub-platform-trust", {"ca-bundle.crt": ingress.rstrip() + "\n" + kube})
else:
    k8s.missing("developer-hub-platform-trust: ingress or service-account CA not readable")

# Main Secret: written only when complete, so the Pod waits instead of
# starting with unresolved ${...} configuration.
kc = k8s.get_secret("keycloak", "keycloak-client-secret-developer-hub") or {}
github = k8s.require(inputs, ["RHDH_GITHUB_APP_ID", "RHDH_GITHUB_APP_CLIENT_ID",
                              "RHDH_GITHUB_APP_CLIENT_SECRET", "RHDH_GITHUB_APP_PRIVATE_KEY"],
                     "developer-hub-secrets (GitHub App for Developer Hub)")
if not kc.get("CLIENT_SECRET"):
    k8s.missing("developer-hub-secrets: keycloak/keycloak-client-secret-developer-hub not published yet")
if github and kc.get("CLIENT_SECRET"):
    k8s.generated(ns, "developer-hub-secrets", ["BACKEND_SECRET", "AUTH_SESSION_SECRET"], extra={
        "GITHUB_APP_ID": github["RHDH_GITHUB_APP_ID"].strip(),
        "GITHUB_APP_CLIENT_ID": github["RHDH_GITHUB_APP_CLIENT_ID"].strip(),
        "GITHUB_APP_CLIENT_SECRET": github["RHDH_GITHUB_APP_CLIENT_SECRET"].strip(),
        "GITHUB_APP_PRIVATE_KEY": github["RHDH_GITHUB_APP_PRIVATE_KEY"],
        "KEYCLOAK_CLIENT_ID": kc.get("CLIENT_ID", "developer-hub"),
        "KEYCLOAK_CLIENT_SECRET": kc["CLIENT_SECRET"],
    })

# Lightspeed MCP token (generated once) and the LiteMaaS key.
k8s.generated(ns, "developer-hub-lightspeed-secrets", ["MCP_TOKEN"])
if os.environ.get("BOX1_LITEMAAS") == "true":
    key = inputs.get("LITEMAAS_API_KEY") or (
        k8s.get_secret(os.environ.get("BOX1_SYSTEM_NAMESPACE", "box1-rhdp-system"), "box1-rhdp-litemaas") or {}).get("apiKey")
    if key:
        k8s.apply_secret(ns, "developer-hub-lightspeed-litemaas", {"VLLM_API_KEY": key.strip()})
    else:
        k8s.missing("developer-hub-lightspeed-litemaas: no LITEMAAS_API_KEY input or box1-rhdp-litemaas Secret")

# Pull credentials for an onboarding plugin published to the internal registry.
package = os.environ.get("BOX1_ONBOARDING_PLUGIN_PACKAGE", "")
registry = os.environ.get("BOX1_REGISTRY_HOST", "")
if package and registry and package.startswith("oci://" + registry + "/"):
    token = (k8s.get_secret("box1-plugins", "rhdh-plugin-puller-token") or {}).get("token")
    if token:
        auth = base64.b64encode(("rhdh-plugin-puller:" + token).encode()).decode()
        k8s.apply_secret(ns, "dynamic-plugins-registry-auth",
                         {"auth.json": json.dumps({"auths": {registry: {"auth": auth}}})})
    else:
        k8s.missing("dynamic-plugins-registry-auth: box1-plugins/rhdh-plugin-puller-token not ready")


def argocd_token():
    """Read-only Argo CD account for the CD tab (port of scripts/provision-connections.py)."""
    current = k8s.get_secret(ns, "developer-hub-platform-secrets") or {}
    if current.get("ARGOCD_AUTH_TOKEN"):
        return
    path = "/apis/argoproj.io/v1beta1/namespaces/openshift-gitops/argocds/openshift-gitops"
    status, argocd = k8s.call("GET", path)
    if status == 404:
        k8s.missing("ARGOCD_AUTH_TOKEN: ArgoCD openshift-gitops not found")
        return
    spec = argocd.get("spec", {})
    policy = (spec.get("rbac") or {}).get("policy") or ""
    wanted = ["p, role:developer-hub-reader, applications, get, default/*, allow",
              "g, developer-hub, role:developer-hub-reader"]
    patch = {}
    if (spec.get("extraConfig") or {}).get("accounts.developer-hub") != "apiKey":
        patch.setdefault("spec", {})["extraConfig"] = {"accounts.developer-hub": "apiKey"}
    missing_lines = [line for line in wanted if line not in policy.splitlines()]
    if missing_lines:
        patch.setdefault("spec", {})["rbac"] = {"policy": "\n".join([policy.rstrip()] + missing_lines).lstrip() + "\n"}
    if patch:
        k8s.call("PATCH", path, patch, "application/merge-patch+json")
        print("ArgoCD openshift-gitops: developer-hub account and reader policy ensured")
    password = (k8s.get_secret("openshift-gitops", "openshift-gitops-cluster") or {}).get("admin.password")
    url = os.environ.get("BOX1_ARGOCD_URL", "")
    if not (password and url and ingress):
        k8s.missing("ARGOCD_AUTH_TOKEN: Argo CD admin secret, URL or router CA not available")
        return
    context = ssl.create_default_context(cadata=ingress)

    def post(api, body, token=None):
        req = urllib.request.Request(url.rstrip("/") + "/api/v1/" + api, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, context=context, timeout=30) as r:
            return json.load(r)

    try:
        session = post("session", {"username": "admin", "password": password})["token"]
        token_id = "developer-hub-" + uuid.uuid4().hex[:12]
        token = post("account/developer-hub/token", {"expiresIn": 90 * 86400, "id": token_id}, session)["token"]
    except Exception as e:  # the account appears after argocd-server reloads its config
        k8s.missing(f"ARGOCD_AUTH_TOKEN: Argo CD API not ready ({type(e).__name__})")
        return
    k8s.apply_secret(ns, "developer-hub-platform-secrets", {"ARGOCD_AUTH_TOKEN": token})
    print(f"Argo CD token {token_id} minted (90 days; delete the Secret to rotate), created "
          + datetime.now(timezone.utc).isoformat())


argocd_token()
k8s.finish()
