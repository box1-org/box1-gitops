#!/usr/bin/env python3
"""Contract tests for the embedded promotion Task's Argo sync gate.

The production client runs inside the Tekton Python step. These tests keep the
state decisions executable without needing cluster credentials or GitHub access.
"""
import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parent
TASK = ROOT / "gitops-promote.yaml"
RBAC = ROOT.parent / "ci" / "argo-sync-rbac.yaml"


def script_text():
    text = TASK.read_text()
    start = text.index("    script: |", text.index("name: promote"))
    lines = text[start:].splitlines()[1:]
    body = []
    for line in lines:
        if line and not line.startswith("      "):
            break
        body.append(line[6:] if line else '')
    return "\n".join(body)


def revision_matches(observed, expected, direct_source=True):
    if not direct_source:
        return True
    values = [observed] if isinstance(observed, str) else (observed or [])
    return expected in values


class PromotionSyncContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = script_text()
        ast.parse(cls.script)

    def test_merge_is_followed_by_sync_before_success_result(self):
        merged = self.script.index("assert merged.get('merged')")
        sync = self.script.index("sync_application(merged['sha']", merged)
        promoted = self.script.index("result('promoted','true')", sync)
        self.assertLess(merged, sync)
        self.assertLess(sync, promoted)

    def test_patch_is_kubernetes_operation_without_destructive_flags(self):
        self.assertIn("'initiatedBy':{'username':'box1-release'}", self.script)
        self.assertIn("'syncStrategy':{'hook':{}}", self.script)
        self.assertNotIn("'prune'", self.script)
        self.assertNotIn("'force'", self.script)
        self.assertNotIn("argocd", self.script.split("def github", 1)[0].lower())

    def test_existing_expected_sync_is_accepted_but_stale_revision_is_rejected(self):
        self.assertTrue(revision_matches("abc", "abc"))
        self.assertTrue(revision_matches(["other", "abc"], "abc"))
        self.assertFalse(revision_matches("old", "abc"))
        self.assertTrue(revision_matches("old", "abc", direct_source=False))

    def test_active_and_terminal_operation_states_are_handled(self):
        self.assertIn("['Running','Terminating']", self.script)
        self.assertIn("['Error','Failed']", self.script)
        self.assertIn("raise TimeoutError(diagnostics(app,expected,'Running'))", self.script)

    def test_multi_source_and_expected_revision_are_handled(self):
        self.assertIn("spec.get('sources')", self.script)
        self.assertIn("sync['revisions']", self.script)
        self.assertIn("expected if source in direct", self.script)
        self.assertIn("https://github.com/box1-org/box1-workloads-dev", self.script)
        self.assertNotIn("directly tracks `box1-gitops`", self.script)
        self.assertIn("ARGO_SYNC_TIMEOUT", self.script)
        self.assertIn("default: '300'", TASK.read_text())

    def test_rbac_is_limited_to_application_get_and_patch(self):
        text = RBAC.read_text()
        self.assertIn("namespace: openshift-gitops", text)
        self.assertIn("- get", text)
        self.assertIn("- patch", text)
        self.assertNotIn("- list", text)
        self.assertNotIn("- update", text)
        self.assertNotIn("- delete", text)


if __name__ == "__main__":
    unittest.main()
