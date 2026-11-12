"""Scenario matrix for check.py."""
import yaml


def _docs(text):
    return [d for d in yaml.safe_load_all(text) if d]


def _find(text, kind, name):
    for d in _docs(text):
        if d.get("kind") == kind and d["metadata"]["name"] == name:
            return d
    return None


def developer_hub(litemaas):
    """Structural checks of the built developer-hub Application."""
    def check(apps, built):
        errors = []
        text = built.get("developer-hub", "")
        bs = _find(text, "Backstage", "developer-hub")
        if not bs:
            return ["developer-hub: Backstage not built"]
        pod = bs["spec"]["deployment"]["patch"]["spec"]["template"]["spec"]
        names = [c["name"] for c in pod["containers"]]
        inits = [c["name"] for c in pod["initContainers"]]
        if litemaas:
            if names != ["backstage-backend", "llama-stack", "lightspeed-core"]:
                errors.append(f"developer-hub: containers {names}")
            refs = [e.get("secretRef", {}).get("name") for e in pod["containers"][1].get("envFrom", [])]
            if "developer-hub-lightspeed-litemaas" not in refs:
                errors.append("developer-hub: llama-stack lacks the LiteMaaS secretRef")
            env = _find(text, "ConfigMap", "developer-hub-llama-stack-env")["data"]
            if "VLLM_API_KEY" in env or not env.get("VLLM_URL", "").startswith("https://litemaas."):
                errors.append(f"developer-hub: llama-stack env not LiteMaaS: {sorted(env)}")
        else:
            if names != ["backstage-backend"] or inits != ["install-dynamic-plugins"]:
                errors.append(f"developer-hub: Lightspeed not removed: {names} {inits}")
        env = _find(text, "ConfigMap", "developer-hub-platform-env")["data"]
        if env.get("BOX1_API_URL") != "https://kubernetes.default.svc":
            errors.append("developer-hub: BOX1_API_URL not in-cluster")
        if "BOX1_ONBOARDING_PLUGIN_PACKAGE" not in env:
            errors.append("developer-hub: onboarding package override missing")
        if bs["spec"]["application"]["route"]["host"] != "developer-hub.apps.cluster-test.example.com":
            errors.append("developer-hub: route host not patched")
        return errors
    return check


def rhtpa_auth(apps, built):
    """rhtpa-auth must equal platform/ except for the issuer."""
    import json
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(root, "platform/trusted-profile-analyzer/instance/auth.yaml")) as f:
        want = json.loads(json.load(f)["data"]["auth.yaml"])
    cm = _find(built.get("rhtpa", ""), "ConfigMap", "rhtpa-auth")
    if not cm:
        return ["rhtpa: rhtpa-auth not built"]
    got = json.loads(cm["data"]["auth.yaml"])
    issuer = "https://sso.apps.cluster-test.example.com/realms/box1"
    for c in want["authentication"]["clients"]:
        c["issuerUrl"] = issuer
    return [] if got == want else ["rhtpa: rhtpa-auth differs from platform/ beyond the issuer"]


def sandboxes(users):
    def check(apps, built):
        names = sorted(d["metadata"]["name"] for d in _docs(built.get("box1-sandboxes", "")) if d["kind"] == "Namespace")
        want = sorted(u + "-sandbox" for u in users)
        return [] if names == want else [f"box1-sandboxes: namespaces {names}, want {want}"]
    return check

OPERATE = ["box1-service-namespaces", "service-mesh-operators", "service-mesh-network",
           "service-mesh-control-plane", "service-mesh-kiali", "observability-operators",
           "user-workload-monitoring", "observability-tracing", "observability-console",
           "observability-dashboards"]
DEVELOPER = ["box1-service-namespaces", "pipelines-operator", "registry-default-route",
             "pipelines-config", "pipelines-ci", "developer-hub-operator", "developer-hub",
             "dev-spaces-operator", "dev-spaces", "reposilite", "mailhog", "box1-workloads-dev"]

SECURITY_BASE = ["acs-operator", "acs", "rhtpa-operator"]

# Text in built manifests that legitimately mentions homelab values.
DEV_ALLOW = {
    # Homelab defaults inside Task scripts and param descriptions; RHDP
    # supplies box1-platform-settings, which takes precedence.
    # The homelab values in developer-hub-platform-env are replaced by the
    # root chart's patch; the onboarding plugin entry is dropped at install time.
    "developer-hub": [r"registry\.apps\.ocp\.box1\.org/box1-plugins/box1-onboarding-plugin", r"^\s*#"],
    "pipelines-ci": [r"os\.environ\.get\(", r"env\.get\(.BOX1_", r"\$\{BOX1_[A-Z_]+:-", r"description: ", r"^\s*#",
                     r"box1-org/box1-docs#", r"^\s*else https://", r'^\s*"""', r"empty means BOX1_"],
}


def SCENARIOS(Scenario, sentinel):
    allp = {"core": True, "rhbk": True, "developer": True, "operate": True, "security": True, "ai": True}
    litemaas = {"enabled": True, "apiUrl": "https://litemaas.example.com/v1", "apiKey": sentinel, "model": "llama-scout-17b"}
    return [
        Scenario("default (core + rhbk)", {}, expect=["keycloak-rhbk"]),
        Scenario(
            "security, no object store",
            {"profiles": {"security": True}},
            expect=SECURITY_BASE,
            absent=["rhtpa-prerequisites", "rhtpa"],
        ),
        Scenario(
            "security, odf, cert-manager TLS",
            {"profiles": {"security": True}, "storage": {"objectStore": "odf"},
             "security": {"rhtpa": {"tls": "certManager", "clusterIssuer": "rhdp-issuer"}}},
            expect=SECURITY_BASE + ["rhtpa-prerequisites", "rhtpa"],
            check=rhtpa_auth,
        ),
        Scenario(
            "ai without LiteMaaS",
            {"profiles": {"ai": True}, "storage": {"objectStore": "odf"}},
            expect=["langfuse"],
            absent=["lightspeed-operator", "lightspeed"],
        ),
        Scenario(
            "all profiles, odf, LiteMaaS, demo org",
            {"profiles": allp, "git": {"org": "box1-rhdp"}, "litemaas": litemaas,
             "storage": {"objectStore": "odf", "rwoClass": "gp3-csi"},
             "ci": {"builderImage": "quay.io/box1-rhdp/box1-builder@sha256:" + "b" * 64},
             "developerHub": {"onboardingPluginPackage": "oci://quay.io/box1-rhdp/box1-onboarding-plugin@sha256:" + "c" * 64 + "!box1-scaffolder-onboarding"}},
            expect=DEVELOPER + OPERATE + SECURITY_BASE + ["observability-logging", "rhtpa-prerequisites", "rhtpa",
                                                         "lightspeed-operator", "lightspeed", "langfuse"],
            allow=DEV_ALLOW,
            check=lambda a, b: developer_hub(litemaas=True)(a, b) + rhtpa_auth(a, b),
        ),
        Scenario(
            "kafka enabled",
            {"components": {"kafkaOperator": {"enabled": True}, "kafka": {"enabled": True}}},
            expect=["kafka-operator", "box1-kafka"],
        ),
        Scenario(
            "operate, no object store",
            {"profiles": {"operate": True}},
            expect=OPERATE,
            absent=["observability-logging"],
        ),
        Scenario(
            "operate, odf + rwoClass",
            {"profiles": {"operate": True}, "storage": {"objectStore": "odf", "rwoClass": "gp3-csi"}},
            expect=OPERATE + ["observability-logging"],
        ),
        Scenario(
            "developer, demo org, published builder",
            {"profiles": {"developer": True}, "git": {"org": "box1-rhdp"},
             "ci": {"builderImage": "quay.io/box1-rhdp/box1-builder@sha256:" + "a" * 64}},
            expect=DEVELOPER,
            allow=DEV_ALLOW,
            check=developer_hub(litemaas=False),
        ),
        Scenario(
            "developer + LiteMaaS + multi-user sandboxes",
            {"profiles": {"developer": True}, "git": {"org": "box1-rhdp"},
             "litemaas": {"enabled": True, "apiUrl": "https://litemaas.example.com/v1", "apiKey": sentinel,
                          "model": "llama-scout-17b"},
             "devSpaces": {"sandboxes": True},
             "multi_user": {"num_users": 2, "users": [{"username": "user1"}, {"username": "user2"}]}},
            expect=DEVELOPER + ["box1-sandboxes"],
            allow=DEV_ALLOW,
            check=lambda a, b: developer_hub(litemaas=True)(a, b) + sandboxes(["user1", "user2"])(a, b),
        ),
        Scenario(
            "developer, cluster-provided Pipelines, external registry",
            {"profiles": {"developer": True}, "git": {"org": "box1-rhdp"},
             "operators": {"subscriptions": {"pipelines": {"manage": False}}},
             "registry": {"host": "quay.io"}},
            expect=["pipelines-config", "pipelines-ci"],
            absent=["pipelines-operator", "registry-default-route"],
            allow=DEV_ALLOW,
        ),
    ]
