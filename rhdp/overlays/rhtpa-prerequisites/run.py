"""RHTPA database and CI client Secrets. Values are never printed."""
import os

import k8s

ns = k8s.NAMESPACE
k8s.generated(ns, "rhtpa-database", ["password", "admin-password"])
client = k8s.get_secret("keycloak", "keycloak-client-secret-rhtpa-ci") or {}
if client.get("CLIENT_SECRET"):
    k8s.apply_secret(ns, "rhtpa-ci", {
        "client-id": client.get("CLIENT_ID", "rhtpa-ci"),
        "client-secret": client["CLIENT_SECRET"],
        "issuer-url": os.environ["BOX1_OIDC_ISSUER"],
    })
else:
    k8s.missing("rhtpa-ci: keycloak/keycloak-client-secret-rhtpa-ci not published yet")
k8s.finish()
