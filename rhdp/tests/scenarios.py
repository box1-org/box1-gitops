"""Scenario matrix for check.py."""

ALL_PROFILES = {"core": True, "rhbk": True, "developer": True, "operate": True, "security": True, "ai": True}


def SCENARIOS(Scenario, sentinel):
    return [
        Scenario(
            "default (core + rhbk)",
            {},
            expect=["keycloak-rhbk"],
        ),
    ]
