"""Credentials for box1-ci Tasks on RHDP. Values are never printed."""
import base64
import json
import os
import ssl
import urllib.request

import k8s

ns = k8s.NAMESPACE
inputs = k8s.inputs()
profiles = set(filter(None, os.environ.get("BOX1_PROFILES", "").split(",")))
optional = set(filter(None, os.environ.get("BOX1_CI_OPTIONAL", "").split(",")))

# registry.redhat.io pull credentials (base images, site images, bootc).
config = inputs.get("REDHAT_REGISTRY_DOCKERCONFIGJSON")
if not config:
    cluster = k8s.get_secret("openshift-config", "pull-secret") or {}
    auths = json.loads(cluster.get(".dockerconfigjson", "{}")).get("auths", {})
    if "registry.redhat.io" in auths:
        config = json.dumps({"auths": {"registry.redhat.io": auths["registry.redhat.io"]}})
if config:
    k8s.apply_secret(ns, "redhat-registry-pull", {".dockerconfigjson": config}, "kubernetes.io/dockerconfigjson")
else:
    k8s.missing("redhat-registry-pull: no registry.redhat.io entry in the cluster pull secret "
                "and no REDHAT_REGISTRY_DOCKERCONFIGJSON input")

# RHTPA ingestion client for the security gates (published by keycloak-rhbk).
if "rhbk" in profiles:
    client = k8s.get_secret("keycloak", "keycloak-client-secret-rhtpa-ci")
    if client and client.get("CLIENT_SECRET"):
        k8s.apply_secret(ns, "rhtpa-secret", {"client-secret": client["CLIENT_SECRET"]})
    else:
        k8s.missing("rhtpa-secret: keycloak/keycloak-client-secret-rhtpa-ci not published yet")

# RHACS: Central CA and a Continuous Integration API token.
if "security" in profiles:
    tls = k8s.get_secret("stackrox", "central-tls")
    if not tls or not tls.get("ca.pem"):
        k8s.missing("rhacs-central-ca: stackrox/central-tls not available yet")
    else:
        k8s.apply_configmap(ns, "rhacs-central-ca", {"ca.pem": tls["ca.pem"]})
        if not (k8s.get_secret(ns, "rhacs-secret") or {}).get("rox-api-token"):
            admin = k8s.get_secret("stackrox", "central-htpasswd") or {}
            if not admin.get("password"):
                k8s.missing("rhacs-secret: stackrox/central-htpasswd not available yet")
            else:
                ctx = ssl.create_default_context(cadata=tls["ca.pem"])
                ctx.check_hostname = False  # Central's certificate names central.stackrox, not the Service FQDN
                req = urllib.request.Request(
                    "https://central.stackrox.svc:443/v1/apitokens/generate",
                    data=json.dumps({"name": "box1-ci-security-gates", "roles": ["Continuous Integration"]}).encode(),
                    method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", "Basic " + base64.b64encode(
                    ("admin:" + admin["password"]).encode()).decode())
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                        token = json.loads(r.read())["token"]
                    k8s.apply_secret(ns, "rhacs-secret", {"rox-api-token": token})
                except Exception as e:  # Central may still be starting
                    k8s.missing(f"rhacs-secret: Central API not ready ({type(e).__name__})")

# Optional bootc/ERP inputs.
if "bootc" in optional:
    ent = k8s.get_secret("openshift-config-managed", "etc-pki-entitlement")
    if not ent and inputs.get("ENTITLEMENT_CERT") and inputs.get("ENTITLEMENT_KEY"):
        ent = {"entitlement.pem": inputs["ENTITLEMENT_CERT"], "entitlement-key.pem": inputs["ENTITLEMENT_KEY"]}
    if ent:
        k8s.apply_secret(ns, "etc-pki-entitlement", ent)
    else:
        k8s.missing("etc-pki-entitlement: cluster has no entitlement and ENTITLEMENT_CERT/KEY inputs are empty")
    for secret, key in (("legacy-erp-deploy-ssh", "LEGACY_ERP_SSH_KEY"), ("vm-instance-status-ssh", "VM_STATUS_SSH_KEY")):
        if inputs.get(key):
            k8s.apply_secret(ns, secret, {"ssh-privatekey": inputs[key]}, "kubernetes.io/ssh-auth")
        else:
            k8s.missing(f"{secret}: input {key} is empty")

k8s.finish()
