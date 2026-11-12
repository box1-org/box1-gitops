"""Scenario matrix for check.py."""

OPERATE = ["box1-service-namespaces", "service-mesh-operators", "service-mesh-network",
           "service-mesh-control-plane", "service-mesh-kiali", "observability-operators",
           "user-workload-monitoring", "observability-tracing", "observability-console",
           "observability-dashboards"]
DEVELOPER = ["box1-service-namespaces", "pipelines-operator", "registry-default-route",
             "pipelines-config", "pipelines-ci"]

# Text in built manifests that legitimately mentions homelab values.
DEV_ALLOW = {
    # Homelab defaults inside Task scripts and param descriptions; RHDP
    # supplies box1-platform-settings, which takes precedence.
    "pipelines-ci": [r"os\.environ\.get\(", r"env\.get\(.BOX1_", r"\$\{BOX1_[A-Z_]+:-", r"description: ", r"^\s*#",
                     r"box1-org/box1-docs#", r"^\s*else https://", r'^\s*"""', r"empty means BOX1_"],
}


def SCENARIOS(Scenario, sentinel):
    return [
        Scenario("default (core + rhbk)", {}, expect=["keycloak-rhbk"]),
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
