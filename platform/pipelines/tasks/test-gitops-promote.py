#!/usr/bin/env python3
"""Contract tests for the embedded promotion Task's Argo sync gate.

The production client runs inside the Tekton Python step. These tests keep the
state decisions executable without needing cluster credentials or GitHub access.
"""
import ast
import pathlib
import re
import types
import unittest
import urllib.parse


ROOT = pathlib.Path(__file__).parent
TASK = ROOT / "gitops-promote.yaml"
RBAC = ROOT.parent / "ci" / "argo-sync-rbac.yaml"
SMOKE = ROOT / "quarkus-smoke.yaml"


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
        # box1-docs#42: the timeout reports the observed phase, never a fixed 'Running'.
        self.assertIn("raise TimeoutError(diagnostics(app,expected))", self.script)
        self.assertNotIn("diagnostics(app,expected,'Running')", self.script)

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


def promotion_functions(text=None, task=TASK):
    """Load only the pure helper definitions from a Task script (no network code runs)."""
    import re
    tree = ast.parse(text if text is not None else script_text())
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in (
                "candidate_paths", "plan_updates", "plan_instance_updates", "evaluate_checks", "converged", "diagnostics", "settled"))
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in (
                "ZERO", "START_FAILURE", "MAX_START_RETRIES", "GENERATED_CONFIGMAP") for t in n.targets))]
    namespace = {"re": re, "name": "order-service"}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(task), "exec"), namespace)
    return namespace


def smoke_script_text():
    text = SMOKE.read_text()
    start = text.index("    script: |")
    body = []
    for line in text[start:].splitlines()[1:]:
        if line and not line.startswith("      "):
            break
        body.append(line[6:] if line else '')
    return "\n".join(body)


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


class VmInstancePromotionPlan(unittest.TestCase):
    """box1-docs#139: a vm-instance promotion edits one instance; the source repo gates supersession."""
    SOURCE = "d" * 40
    DIGEST = "sha256:" + "e" * 64
    DISK = "sha256:" + "f" * 64
    NEXT_DIGEST = "sha256:" + "1" * 64
    NEXT_DISK = "sha256:" + "2" * 64

    @classmethod
    def setUpClass(cls):
        import importlib.util
        cls.f = promotion_functions()
        spec = importlib.util.spec_from_file_location("vt", ROOT / "test-gitops-validate.py")
        cls.vt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.vt)

    def repo(self, promoted=False):
        """Two instances of one source image, as box1-workloads-dev would hold them."""
        import textwrap
        tree = {}
        for instance in ["site-west", "site-east"]:
            _, files = self.vt.instance_bundle(instance, promoted=promoted)
            for path, content in files.items():
                tree["workloads/" + instance + "/" + path] = textwrap.dedent(content).lstrip()
        return tree

    def plan(self, tree, instance, disk, digest=None, run="site-gateway-os-release-abcde"):
        paths = self.f["candidate_paths"]("vm-instance", instance)
        old = {p: tree[p] for p in paths}
        return paths, self.f["plan_instance_updates"](instance, "site-gateway-os", old, self.SOURCE, digest or self.DIGEST, disk, run)

    def validates(self, tree, instance, new):
        if not self.vt.KUSTOMIZE:
            return
        base = "workloads/" + instance + "/"
        files = {p[len(base):]: c for p, c in tree.items() if p.startswith(base)}
        files.update({p[len(base):]: c for p, c in new.items()})
        self.assertEqual(self.vt.load_validator()["validate"](instance, self.vt.render(files)), "vm-instance")

    def test_candidate_paths_are_the_instance_files(self):
        self.assertEqual(self.f["candidate_paths"]("vm-instance", "site-west"),
                         ["workloads/site-west/virtualmachine.yaml", "workloads/site-west/datavolume.yaml",
                          "workloads/site-west/kustomization.yaml"])

    def test_first_promotion_of_one_instance_changes_only_that_instance(self):
        tree = self.repo()
        paths, new = self.plan(tree, "site-west", self.DISK)
        self.assertEqual(sorted(new), ["workloads/site-west/datavolume.yaml", "workloads/site-west/kustomization.yaml",
                                       "workloads/site-west/virtualmachine.yaml"])
        self.assertTrue(all(p.startswith("workloads/site-west/") for p in paths))
        vm = new["workloads/site-west/virtualmachine.yaml"]
        self.assertIn("box1.org/os-image-digest: " + self.DIGEST, vm)
        self.assertIn("box1.org/source-revision: " + self.SOURCE, vm)
        self.assertIn("box1.org/build-pipelinerun: box1-ci/site-gateway-os-release-abcde", vm)
        self.assertIn("box1.org/source-image: site-gateway-os", vm)
        self.assertIn("runStrategy: Always", vm)
        self.assertIn("box1-ci/site-gateway-os-disk@" + self.DISK, new["workloads/site-west/datavolume.yaml"])
        self.assertIn("  - datavolume.yaml", new["workloads/site-west/kustomization.yaml"])
        self.validates(tree, "site-west", new)
        # The sibling instance of the same source is untouched and still unbuilt.
        self.assertIn("box1.org/os-image-digest: sha256:" + "0" * 64, tree["workloads/site-east/virtualmachine.yaml"])

    def test_day2_promotion_changes_only_the_instance_annotations(self):
        tree = self.repo(promoted=True)
        _, new = self.plan(tree, "site-east", self.NEXT_DISK, digest=self.NEXT_DIGEST, run="site-gateway-os-release-fghij")
        self.assertEqual(sorted(new), ["workloads/site-east/virtualmachine.yaml"])
        vm = new["workloads/site-east/virtualmachine.yaml"]
        self.assertIn("box1.org/os-image-digest: " + self.NEXT_DIGEST, vm)
        self.assertIn("runStrategy: Always", vm)
        self.assertEqual(vm.replace(self.NEXT_DIGEST, "X").count("X"), 1)
        self.validates(tree, "site-east", new)

    def test_first_promotion_requires_a_disk_digest(self):
        tree = self.repo()
        for disk in ["", "sha256:" + "0" * 64, "latest"]:
            with self.assertRaisesRegex(AssertionError, "disk digest"):
                self.plan(tree, "site-west", disk)

    def test_source_annotation_must_match_the_promoting_repository(self):
        tree = self.repo()
        paths = self.f["candidate_paths"]("vm-instance", "site-west")
        old = {p: tree[p] for p in paths}
        with self.assertRaisesRegex(AssertionError, "box1.org/source-image: legacy-erp"):
            self.f["plan_instance_updates"]("site-west", "legacy-erp", old, self.SOURCE, self.DIGEST, self.DISK, "run")

    def test_unbuilt_datavolume_must_reference_the_source_disk(self):
        tree = self.repo()
        dv = "workloads/site-west/datavolume.yaml"
        tree[dv] = tree[dv].replace("site-gateway-os-disk@", "site-west-disk@")
        with self.assertRaisesRegex(AssertionError, "zero site-gateway-os-disk digest"):
            self.plan(tree, "site-west", self.DISK)

    def test_existing_profiles_do_not_use_the_instance_plan(self):
        script = script_text()
        self.assertIn("plan_instance_updates(name,source_image,old,", script)
        self.assertIn("if profile=='vm-instance' else plan_updates(profile,name,old,", script)

    def test_task_contract_for_instance_promotions(self):
        task = TASK.read_text()
        self.assertIn("  - name: instance-name\n    type: string\n    default: ''", task)
        self.assertIn('value: "$(params.instance-name)"', task)
        script = script_text()
        # Supersession is judged on the source repository (application-name) ...
        source_repo = script.index("application='/repos/'+GIT_ORG+'/'+name")
        retarget = script.index("source_image,name=name,instance")
        self.assertLess(source_repo, retarget)
        # ... and every later use of `name` (files, branch, PR, Argo sync) is the instance.
        self.assertLess(retarget, script.index("def sync_application"))
        self.assertLess(retarget, script.index("candidates=candidate_paths(profile,name)"))
        self.assertIn("assert profile in ['service','virtual-machine','vm-instance'], 'Unsupported workload profile'", script)
        self.assertIn("assert not instance, 'instance-name is only valid with workload-profile vm-instance'", script)


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


class GeneratedConfigMapOrphans(unittest.TestCase):
    """box1-docs#42: a configMapGenerator change must not fail a healthy release.

    Changing a literal renames the generated ConfigMap. Workload Applications do not
    prune, so the old one stays live and keeps the Application OutOfSync.
    """
    EXPECTED = "5fd61de" + "0" * 33

    @classmethod
    def setUpClass(cls):
        cls.f = promotion_functions()
        cls.smoke = promotion_functions(smoke_script_text(), SMOKE)

    def res(self, name, kind="ConfigMap", status="OutOfSync", prune=True, group=""):
        r = {"group": group, "version": "v1", "kind": kind, "namespace": "order-service", "name": name, "status": status}
        if prune:
            r["requiresPruning"] = True
        return r

    def app(self, sync="OutOfSync", health="Healthy", resources=(), phase="Succeeded"):
        return {"status": {"sync": {"status": sync, "revision": self.EXPECTED}, "health": {"status": health},
                           "operationState": {"phase": phase}, "resources": list(resources)}}

    def both(self, status):
        promote = self.f["converged"](status)
        self.assertEqual(promote, self.smoke["converged"](status), "promote and smoke must agree")
        return promote

    def test_observed_orphans_are_tolerated(self):
        # Names from order-service-release-dq2fk and the 2026-11-06 cleanup.
        for orphan in ["order-service-config-29d2hgcc29", "order-service-config-8btd4c24mh",
                       "inventory-service-config-cb8h282db5", "fulfillment-adapter-config-89db8g96gh"]:
            status = self.app(resources=[self.res("order-service", kind="Deployment", status="Synced", prune=False, group="apps"),
                                         self.res(orphan)])["status"]
            self.assertEqual(self.both(status), (True, ["order-service/" + orphan]))
        self.assertTrue(self.f["settled"](self.app(resources=[self.res("order-service-config-29d2hgcc29")]), self.EXPECTED, True))

    def test_synced_is_unchanged(self):
        self.assertEqual(self.both(self.app(sync="Synced")["status"]), (True, []))

    def test_real_drift_still_fails(self):
        cases = {
            "modified live object": [self.res("order-service", kind="Deployment", prune=False, group="apps")],
            "missing generated ConfigMap": [self.res("order-service-config-29d2hgcc29", prune=False)],
            "orphan plus real drift": [self.res("order-service-config-29d2hgcc29"),
                                       self.res("order-service", kind="Service", prune=False)],
            "pruning a non-generated ConfigMap": [self.res("order-service-config")],
            "pruning another kind": [self.res("order-service-db-29d2hgcc29", kind="Secret")],
            "pruning a PVC": [self.res("postgres-data", kind="PersistentVolumeClaim")],
            "pruning a grouped kind": [self.res("order-service-config-29d2hgcc29", group="example.com")],
            "OutOfSync with no resource detail": [],
        }
        for label, resources in cases.items():
            with self.subTest(label):
                self.assertEqual(self.both(self.app(resources=resources)["status"]), (False, []))
        for sync in ["Unknown", None]:
            self.assertEqual(self.both(self.app(sync=sync)["status"]), (False, []))

    def test_unhealthy_or_wrong_revision_still_fails(self):
        orphan = [self.res("order-service-config-29d2hgcc29")]
        self.assertFalse(self.f["settled"](self.app(health="Degraded", resources=orphan), self.EXPECTED, True))
        self.assertFalse(self.f["settled"](self.app(resources=orphan), "f" * 40, True))

    def test_diagnostics_report_the_observed_phase_and_drift(self):
        app = self.app(resources=[self.res("order-service", kind="Deployment", prune=False, group="apps")])
        message = self.f["diagnostics"](app, self.EXPECTED)
        self.assertIn("operation phase=Succeeded", message)
        self.assertNotIn("phase=Running", message)
        self.assertIn("out-of-sync resources=Deployment/order-service", message)
        app["status"]["operationState"] = {}
        self.assertIn("operation phase=none", self.f["diagnostics"](app, self.EXPECTED))

    def test_smoke_uses_the_tolerance(self):
        script = smoke_script_text()
        self.assertIn("synced,orphans=converged(app.get('status',{}))", script)
        self.assertNotIn("get('status')=='Synced'", script)


def settings_namespace(script, env, names, functions=()):
    """Run only the named top-level assignments and helpers of a Task script against `env`.

    `env` stands in for the step's environment, including the optional
    box1-platform-settings ConfigMap (box1-docs#165); no network code runs.
    """
    tree = ast.parse(script)
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in functions)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in names for t in n.targets))]
    namespace = {"os": types.SimpleNamespace(environ=dict(env)), "re": re, "urllib": urllib, "name": "order-service"}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "settings", "exec"), namespace)
    return namespace


ENVFROM = "    envFrom:\n    - configMapRef:\n        name: box1-platform-settings\n        optional: true\n"


class PlatformSettings(unittest.TestCase):
    """box1-docs#165: RHDP values come from box1-platform-settings; without it the homelab literals apply."""

    NAMES = ("GIT_ORG", "WORKLOADS_REPO_URL", "application", "gitops")
    RHDP = {"BOX1_GIT_ORG": "box1-rhdp", "BOX1_WORKLOADS_REPO_URL": "https://github.com/box1-rhdp/box1-workloads-dev.git",
            "BOX1_APPS_DOMAIN": "apps.cluster-abcde.dynamic.redhatworkshops.io"}

    def promote(self, env):
        return settings_namespace(script_text(), env, self.NAMES, ("repo_slug", "tracks_workloads"))

    def test_steps_read_the_optional_settings_configmap(self):
        for task in [TASK, SMOKE]:
            self.assertEqual(task.read_text().count(ENVFROM), 1, task.name)

    def test_homelab_defaults_are_unchanged_without_the_configmap(self):
        ns = self.promote({})
        self.assertEqual(ns["application"], "/repos/box1-org/order-service")
        self.assertEqual(ns["gitops"], "/repos/box1-org/box1-workloads-dev")
        self.assertTrue(ns["tracks_workloads"]({"repoURL": "https://github.com/box1-org/box1-workloads-dev.git"}))
        self.assertFalse(ns["tracks_workloads"]({"repoURL": "https://github.com/box1-org/box1-gitops"}))
        smoke = settings_namespace(smoke_script_text(), {}, ("APPS_DOMAIN",))
        self.assertEqual(smoke["APPS_DOMAIN"], "apps.ocp.box1.org")

    def test_rhdp_org_workloads_repository_and_domain_come_from_the_configmap(self):
        ns = self.promote(self.RHDP)
        self.assertEqual(ns["application"], "/repos/box1-rhdp/order-service")
        self.assertEqual(ns["gitops"], "/repos/box1-rhdp/box1-workloads-dev")
        self.assertTrue(ns["tracks_workloads"]({"repoURL": "https://github.com/box1-rhdp/box1-workloads-dev/"}))
        self.assertFalse(ns["tracks_workloads"]({"repoURL": "https://github.com/box1-org/box1-workloads-dev"}))
        smoke = settings_namespace(smoke_script_text(), self.RHDP, ("APPS_DOMAIN",))
        self.assertEqual(smoke["APPS_DOMAIN"], "apps.cluster-abcde.dynamic.redhatworkshops.io")
        self.assertIn("base='https://'+namespace+'.'+APPS_DOMAIN", smoke_script_text())


if __name__ == "__main__":
    unittest.main()
