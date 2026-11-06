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


def promotion_functions():
    """Load only the pure helper definitions from the Task script (no network code runs)."""
    import re
    tree = ast.parse(script_text())
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ("candidate_paths", "plan_updates", "evaluate_checks"))
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("ZERO", "START_FAILURE", "MAX_START_RETRIES") for t in n.targets))]
    namespace = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(TASK), "exec"), namespace)
    return namespace


class PromotionPlan(unittest.TestCase):
    SOURCE = "d" * 40
    DIGEST = "sha256:" + "e" * 64
    DISK = "sha256:" + "f" * 64

    @classmethod
    def setUpClass(cls):
        cls.f = promotion_functions()

    def test_service_profile_edits_are_unchanged(self):
        old = {
            "workloads/svc/kustomization.yaml": "images:\n  - name: svc\n    newName: x\n    digest: sha256:" + "0" * 64 + "\n",
            "workloads/svc/deployment.yaml": "metadata:\n  annotations:\n    box1.org/source-revision: " + "a" * 40
                + "\n    box1.org/build-pipelinerun: awaiting-first-release\nspec:\n  replicas: 0\n",
        }
        self.assertEqual(self.f["candidate_paths"]("service", "svc"), sorted(old, reverse=True))
        new = self.f["plan_updates"]("service", "svc", old, self.SOURCE, self.DIGEST, "", "svc-release-abcde")
        self.assertEqual(sorted(new), sorted(old))
        self.assertIn("    digest: " + self.DIGEST, new["workloads/svc/kustomization.yaml"])
        deployment = new["workloads/svc/deployment.yaml"]
        self.assertIn("box1.org/source-revision: " + self.SOURCE, deployment)
        self.assertIn("box1.org/build-pipelinerun: box1-ci/svc-release-abcde", deployment)
        self.assertIn("  replicas: 1", deployment)

    def vm_old(self, promoted=False):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vt", ROOT / "test-gitops-validate.py")
        vt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vt)
        import textwrap
        name, files = vt.vm_bundle(promoted=promoted)
        base = "workloads/" + name + "/"
        old = {base + p: textwrap.dedent(c).lstrip() for p, c in files.items() if p in ("virtualmachine.yaml", "datavolume.yaml", "kustomization.yaml")}
        return vt, name, files, base, old

    def test_vm_first_promotion_starts_the_vm_and_adds_its_disk(self):
        vt, name, files, base, old = self.vm_old()
        new = self.f["plan_updates"]("virtual-machine", name, old, self.SOURCE, self.DIGEST, self.DISK, "vm-release-abcde")
        self.assertEqual(sorted(new), sorted(old))
        self.assertIn("runStrategy: Always", new[base + "virtualmachine.yaml"])
        self.assertIn("box1.org/os-image-digest: " + self.DIGEST, new[base + "virtualmachine.yaml"])
        self.assertIn(name + "-disk@" + self.DISK, new[base + "datavolume.yaml"])
        self.assertIn("  - datavolume.yaml", new[base + "kustomization.yaml"])
        # The promoted bundle must satisfy the VM profile of box1-gitops-validate.
        if vt.KUSTOMIZE:
            promoted = dict(files)
            promoted.update({p[len(base):]: c for p, c in new.items()})
            self.assertEqual(vt.load_validator()["validate"](name, vt.render(promoted)), "virtual-machine")

    def test_vm_day2_promotion_only_changes_the_vm_annotations(self):
        _, name, _, base, old = self.vm_old(promoted=True)
        new = self.f["plan_updates"]("virtual-machine", name, old, self.SOURCE, self.DIGEST, "", "vm-release-fghij")
        self.assertEqual(sorted(new), [base + "virtualmachine.yaml"])
        vm = new[base + "virtualmachine.yaml"]
        self.assertIn("box1.org/os-image-digest: " + self.DIGEST, vm)
        self.assertIn("runStrategy: Always", vm)
        self.assertEqual(vm.replace(self.DIGEST, "X").count("X"), 1)

    def test_vm_first_promotion_requires_a_disk_digest(self):
        _, name, _, _, old = self.vm_old()
        for disk in ["", "sha256:" + "0" * 64, "latest"]:
            with self.assertRaisesRegex(AssertionError, "disk digest"):
                self.f["plan_updates"]("virtual-machine", name, old, self.SOURCE, self.DIGEST, disk, "run")


class RequiredChecks(unittest.TestCase):
    """box1-docs#64: a PaC 'pipelinerun start failure' is rerequested, not treated as a failed release."""
    VALIDATE = "Pipelines as Code CI / box1-gitops-validate-"
    SMOKE = "Pipelines as Code CI / box1-phase1-smoke-"
    REQUIRED = [SMOKE, VALIDATE]

    @classmethod
    def setUpClass(cls):
        cls.f = promotion_functions()

    def run_(self, id_, name, status="completed", conclusion="success", title="Success", app="box1-pipelines"):
        return {"id": id_, "name": name, "status": status, "conclusion": None if status != "completed" else conclusion,
                "output": {"title": title}, "app": {"slug": app}}

    def evaluate(self, checks, rerequested=()):
        return self.f["evaluate_checks"](checks, self.REQUIRED, set(rerequested))

    def test_all_success_passes(self):
        self.assertEqual(self.evaluate([self.run_(1, self.SMOKE), self.run_(2, self.VALIDATE)]), (True, [], []))

    def test_missing_or_running_check_is_pending(self):
        self.assertEqual(self.evaluate([self.run_(1, self.SMOKE)]), (False, [], []))
        self.assertEqual(self.evaluate([self.run_(1, self.SMOKE), self.run_(2, self.VALIDATE, status="in_progress")]), (False, [], []))

    def test_real_failure_still_fails(self):
        passed, failed, start = self.evaluate([self.run_(1, self.SMOKE), self.run_(2, self.VALIDATE, conclusion="failure", title="Failed")])
        self.assertEqual((passed, failed, start), (False, [self.VALIDATE], []))

    def test_start_failure_is_rerequested_not_failed(self):
        # Observed shape: a stranded queued run, then a newer failed run titled 'pipelinerun start failure'.
        stranded = self.run_(10, self.VALIDATE, status="queued", title="Pending")
        start = self.run_(12, self.VALIDATE, conclusion="failure", title=self.f["START_FAILURE"])
        passed, failed, starts = self.evaluate([self.run_(11, self.SMOKE), stranded, start])
        self.assertEqual((passed, failed), (False, []))
        self.assertEqual([c["id"] for c in starts], [12])

    def test_rerequested_run_is_pending_until_superseded(self):
        start = self.run_(12, self.VALIDATE, conclusion="failure", title=self.f["START_FAILURE"])
        self.assertEqual(self.evaluate([self.run_(11, self.SMOKE), start], rerequested=[12]), (False, [], []))
        rerun = self.run_(20, self.VALIDATE)
        self.assertEqual(self.evaluate([self.run_(11, self.SMOKE), start, rerun], rerequested=[12]), (True, [], []))
        # A rerun that genuinely fails is a real failure.
        bad = self.run_(20, self.VALIDATE, conclusion="failure", title="Failed")
        self.assertEqual(self.evaluate([self.run_(11, self.SMOKE), start, bad], rerequested=[12])[1], [self.VALIDATE])

    def test_other_apps_and_checks_are_ignored(self):
        foreign = self.run_(30, self.VALIDATE, conclusion="failure", title="Failed", app="someone-else")
        other = self.run_(31, "Pipelines as Code CI / unrelated-", conclusion="failure", title="Failed")
        self.assertEqual(self.evaluate([self.run_(1, self.SMOKE), self.run_(2, self.VALIDATE), foreign, other]), (True, [], []))

    def test_loop_rerequests_with_a_bound(self):
        script = script_text()
        self.assertEqual(self.f["MAX_START_RETRIES"], 2)
        self.assertIn("evaluate_checks(checks,required,rerequested)", script)
        self.assertIn("'/check-runs/'+str(check['id'])+'/rerequest','POST'", script)
        self.assertIn("start_retries[check['name']]<=MAX_START_RETRIES", script)
        self.assertIn("check-runs?per_page=100&filter=all", script)


if __name__ == "__main__":
    unittest.main()
