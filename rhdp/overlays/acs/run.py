"""RHACS declarative OIDC provider (acs-oidc-config). Values are never printed."""
import os

import k8s

ns = k8s.NAMESPACE
client = k8s.get_secret("keycloak", "keycloak-client-secret-rhacs-oidc") or {}
if not client.get("CLIENT_SECRET"):
    k8s.missing("acs-oidc-config: keycloak/keycloak-client-secret-rhacs-oidc not published yet")
else:
    domain = os.environ["BOX1_APPS_DOMAIN"]
    admins = [u for u in os.environ.get("BOX1_ADMIN_USERS", "admin").split(",") if u]
    groups = "".join(
        f"  - key: preferred_username\n    value: {u}\n    role: Admin\n" for u in admins)
    provider = (
        "name: Keycloak\n"
        "minimumRole: Analyst\n"
        f"uiEndpoint: acs.{domain}:443\n"
        "groups:\n" + groups +
        "oidc:\n"
        f"  issuer: {os.environ['BOX1_OIDC_ISSUER']}\n"
        "  mode: auto\n"
        f"  clientID: {client.get('CLIENT_ID', 'rhacs-oidc')}\n"
        f"  clientSecret: {client['CLIENT_SECRET']}\n"
    )
    k8s.apply_secret(ns, "acs-oidc-config", {"keycloak-auth-provider.yaml": provider})
k8s.finish()
