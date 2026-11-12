"""Scenario matrix for check.py."""

OPERATE = ["box1-service-namespaces", "service-mesh-operators", "service-mesh-network",
           "service-mesh-control-plane", "service-mesh-kiali", "observability-operators",
           "user-workload-monitoring", "observability-tracing", "observability-console",
           "observability-dashboards"]


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
    ]
