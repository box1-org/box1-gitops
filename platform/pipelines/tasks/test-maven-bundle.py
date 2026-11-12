#!/usr/bin/env python3
"""Contract tests for box1-maven-bundle and box1-bundle-consumer-pr (box1-docs#137).

The production code runs inside Tekton Python steps. These tests extract the step
scripts from the Task YAML and run their functions against temporary directories and
a recorded fake GitHub API, without cluster credentials, GitHub access or a registry.

    python3 platform/pipelines/tasks/test-maven-bundle.py
"""
import ast
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).parent
BUNDLE_TASK = ROOT / "maven-bundle.yaml"
CONSUMER_TASK = ROOT / "bundle-consumer-pr.yaml"
QUARKUS_MAVEN = ROOT / "quarkus-maven.yaml"
# box1-quarkus-maven must stay byte-identical for services (box1-docs#137 guardrail).
# Re-pinned for box1-docs#165: optional box1-platform-settings org/registry with homelab defaults.
QUARKUS_MAVEN_SHA256 = "dc217d28e8e485c5de642223b922789d32ce39281dcbdf4dfdc0f6279880e145"
# box1-docs#165: keys of the optional box1-platform-settings ConfigMap the Tasks read.
PLATFORM_SETTINGS = ["BOX1_APPS_DOMAIN", "BOX1_GIT_HOST", "BOX1_GIT_ORG", "BOX1_GITOPS_REPO_URL", "BOX1_WORKLOADS_REPO_URL",
                     "BOX1_TEMPLATES_REPO_URL", "BOX1_REGISTRY_HOST", "BOX1_OIDC_ISSUER", "BOX1_TPA_URL", "BOX1_ACS_URL"]
RHDP_SETTINGS = {"BOX1_GIT_ORG": "box1-rhdp", "BOX1_GITOPS_REPO_URL": "https://github.com/box1-rhdp/box1-gitops",
                 "BOX1_WORKLOADS_REPO_URL": "https://github.com/box1-rhdp/box1-workloads-dev",
                 "BOX1_REGISTRY_HOST": "default-route-openshift-image-registry.apps.cluster-abcde.dynamic.redhatworkshops.io"}
ENVFROM = "    envFrom:\n    - configMapRef:\n        name: box1-platform-settings\n        optional: true\n"


def settings_env(settings=None):
    """The process environment without any BOX1_* platform setting, plus `settings`."""
    env = {k: v for k, v in os.environ.items() if k not in PLATFORM_SETTINGS}
    env.update(settings or {})
    return env


def step_script(task, step):
    text = task.read_text()
    start = text.index("    script: |", text.index("  - name: " + step + "\n"))
    body = []
    for line in text[start:].splitlines()[1:]:
        if line and not line.startswith("      "):
            break
        body.append(line[6:] if line else "")
    return "\n".join(body)


def load(task, step, settings=None):
    """Load a step script; `settings` stands in for the box1-platform-settings ConfigMap."""
    script = step_script(task, step)
    ast.parse(script)
    namespace = {"__name__": "box1_contract_test"}
    with mock.patch.dict(os.environ, settings_env(settings), clear=True):
        exec(compile(script, str(task) + ":" + step, "exec"), namespace)
    return script, namespace


POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.box1</groupId><artifactId>site-gateway</artifactId><version>1.0.0-SNAPSHOT</version>
  <packaging>%s</packaging>
  <modules>%s</modules>
</project>
"""


def pom(modules, packaging="pom"):
    return POM % (packaging, "".join("<module>%s</module>" % m for m in modules))


def fast_jar(application, module, extra=b""):
    app = pathlib.Path(application) / module / "target" / "quarkus-app"
    for rel, data in {"quarkus-run.jar": b"run-" + module.encode(), "app/" + module + "-1.0.0-SNAPSHOT.jar": b"app" + extra,
                      "lib/main/io.quarkus.quarkus-core-3.40.1.1.jar": b"core", "quarkus/quarkus-application.dat": b"dat"}.items():
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_bytes(data)
    return app


class MavenBundleTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script, cls.ns = load(BUNDLE_TASK, "verify-and-package")
        cls.push = step_script(BUNDLE_TASK, "push")

    def test_quarkus_maven_is_unchanged_for_services(self):
        self.assertEqual(hashlib.sha256(QUARKUS_MAVEN.read_bytes()).hexdigest(), QUARKUS_MAVEN_SHA256)

    def test_modules_come_from_the_parent_pom_in_order(self):
        self.assertEqual(self.ns["modules_of"](pom(["gateway", "ops", "simulator"])), ["gateway", "ops", "simulator"])

    def test_invalid_parent_poms_fail_clearly(self):
        cases = {pom(["gateway"], "jar"): "parent POM", pom([]): "declares no <modules>",
                 pom(["../escape"]): "must be a directory name", pom(["Gateway"]): "must be a directory name",
                 pom(["a/b"]): "must be a directory name", pom(["ops", "ops"]): "lists a module twice"}
        for text, message in cases.items():
            with self.assertRaises(SystemExit) as raised:
                self.ns["modules_of"](text)
            self.assertIn(message, str(raised.exception))

    def build(self, application, modules, revision="a" * 40, extra=b""):
        for module in modules:
            fast_jar(application, module, extra)
        work = pathlib.Path(tempfile.mkdtemp())
        self.ns["stage"](application, modules, work / "bundle")
        return work, self.ns["make_layout"](work / "bundle", work / "oci", revision, "box1-org/site-gateway", modules)

    def test_layout_is_one_scratch_layer_with_module_fast_jars(self):
        with tempfile.TemporaryDirectory() as application:
            work, digest = self.build(application, ["gateway", "ops", "simulator"])
            oci = work / "oci"
            index = json.loads((oci / "index.json").read_text())
            self.assertEqual(index["manifests"][0]["digest"], digest)
            manifest = json.loads((oci / "blobs/sha256" / digest.split(":")[1]).read_bytes())
            self.assertEqual(hashlib.sha256((oci / "blobs/sha256" / digest.split(":")[1]).read_bytes()).hexdigest(), digest.split(":")[1])
            self.assertEqual(len(manifest["layers"]), 1, "FROM scratch: exactly one layer, no base image")
            self.assertEqual(manifest["annotations"]["org.opencontainers.image.revision"], "a" * 40)
            self.assertEqual(manifest["annotations"]["org.box1.bundle.modules"], "gateway,ops,simulator")
            layer = (oci / "blobs/sha256" / manifest["layers"][0]["digest"].split(":")[1]).read_bytes()
            with tarfile.open(fileobj=io.BytesIO(gzip.decompress(layer))) as tar:
                members = tar.getmembers()
            names = [m.name for m in members]
            for module in ["gateway", "ops", "simulator"]:
                self.assertIn(module + "/quarkus-app/quarkus-run.jar", names)
                self.assertIn(module + "/quarkus-app/lib/main/io.quarkus.quarkus-core-3.40.1.1.jar", names)
            self.assertIn("SHA256SUMS", names)
            self.assertEqual({n.split("/")[0] for n in names}, {"gateway", "ops", "simulator", "SHA256SUMS"},
                             "only /<module>/quarkus-app/ and /SHA256SUMS at the image root")
            self.assertTrue(all(m.mtime == 315532800 and m.uid == 0 and m.gid == 0 and not m.issym() for m in members))
            sums = (work / "bundle" / "SHA256SUMS").read_text()
            self.assertIn("./gateway/quarkus-app/quarkus-run.jar", sums)
            self.assertEqual(sums.count("\n"), len([m for m in members if m.isfile()]) - 1)

    def test_same_output_gives_same_digest_and_a_change_does_not(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two, tempfile.TemporaryDirectory() as three:
            _, first = self.build(one, ["gateway", "ops"])
            _, again = self.build(two, ["gateway", "ops"])
            _, changed = self.build(three, ["gateway", "ops"], extra=b"!")
            self.assertEqual(first, again)
            self.assertNotEqual(first, changed)
            with tempfile.TemporaryDirectory() as four:
                _, other_revision = self.build(four, ["gateway", "ops"], revision="b" * 40)
            self.assertNotEqual(first, other_revision, "the revision label is part of the image")

    def test_a_module_without_a_fast_jar_fails(self):
        with tempfile.TemporaryDirectory() as application:
            fast_jar(application, "gateway")
            with self.assertRaises(SystemExit) as raised:
                self.ns["stage"](application, ["gateway", "ops"], pathlib.Path(application) / "bundle")
            self.assertIn("Module ops has no Quarkus fast-jar", str(raised.exception))

    def test_symlinks_in_build_output_are_refused(self):
        with tempfile.TemporaryDirectory() as application:
            app = fast_jar(application, "gateway")
            (app / "lib" / "escape").symlink_to("/etc/passwd")
            with self.assertRaises(SystemExit) as raised:
                self.ns["stage"](application, ["gateway"], pathlib.Path(application) / "bundle")
            self.assertIn("Refusing symlink", str(raised.exception))

    def test_main_runs_multi_module_verify_and_publishes_only_on_push(self):
        self.assertIn("'verify','-DskipITs=false'", self.script)
        self.assertIn("result('image-digest','not-published')", self.script)
        self.assertIn("if os.environ['PUSH_IMAGE']=='true':", self.script)

    def test_push_is_unprivileged_digest_checked_and_skipped_for_pull_requests(self):
        self.assertTrue(self.push.index('if [ "$PUSH_IMAGE" != true ]') < self.push.index("serviceaccount/token"),
                        "pull requests (ci-test, no token) must exit before reading a token")
        self.assertIn("--digestfile /workspace/pushed-digest", self.push)
        self.assertIn("--preserve-digests", self.push)
        self.assertIn('image="${BOX1_REGISTRY_HOST:-registry.apps.ocp.box1.org}/box1-ci/$IMAGE_NAME"', self.push)
        self.assertIn('"$(cat /workspace/expected-digest)"', self.push)
        self.assertNotIn("tls-verify=false", self.push)
        push_env = BUNDLE_TASK.read_text().split("  - name: push\n", 1)[1]
        for line in ['value: "/tmp/push-home"', 'name: REGISTRY_AUTH_FILE', 'name: CONTAINERS_REGISTRIES_CONF']:
            self.assertIn(line, push_env, "the push step must not read configuration the mvn step could write")
        self.assertRegex(self.push, r"\^\[a-z\]\[a-z0-9-\]\{2,39\}-bundle\$")
        task = BUNDLE_TASK.read_text()
        self.assertNotRegex(task, r"privileged:\s*true|allowPrivilegeEscalation:\s*true|runAsUser:\s*0\b")
        self.assertNotIn("securityContext", task)


CONTAINERFILE = """FROM registry.redhat.io/rhel10/rhel-bootc:10.2@sha256:%s
RUN dnf -y install java-21-openjdk-headless && dnf clean all
COPY --from=registry.apps.ocp.box1.org/box1-ci/site-gateway-bundle@sha256:%s / /usr/lib/site-gateway/
COPY --from=registry.apps.ocp.box1.org/box1-ci/site-gateway-bundle2@sha256:%s / /usr/lib/other/
RUN bootc container lint
""" % ("c" * 64, "0" * 64, "d" * 64)
NEW = "sha256:" + "1" * 64
SOURCE_SHA = "a" * 40
BUNDLE_SHA = "e" * 40


class FakeGitHub:
    """Recorded GitHub API for one consumer and source repository."""

    def __init__(self, files=None, source_main=SOURCE_SHA, open_prs=None, branch_exists=False, consumer_exists=True, branch_tip="Bump site-gateway-bundle to sha256:0000"):
        self.files = {("main-sha", "Containerfile"): CONTAINERFILE, **(files or {})}
        self.source_main, self.prs, self.branch_exists, self.consumer_exists = source_main, open_prs or [], branch_exists, consumer_exists
        self.calls, self.writes, self.branch_tip = [], [], branch_tip

    def __call__(self, path, method="GET", body=None, missing=False):
        self.calls.append((method, path))
        if method != "GET":
            self.writes.append((method, path, body))
        consumer = "/repos/box1-org/site-gateway-os"
        if path == "/repos/box1-org/site-gateway/commits/main":
            return {"sha": self.source_main}
        if path == consumer:
            return {"default_branch": "main"} if self.consumer_exists else None
        if path == consumer + "/git/ref/heads/main":
            return {"object": {"sha": "main-sha"}}
        match = re.fullmatch(re.escape(consumer) + r"/contents/(.+)\?ref=(.+)", path)
        if match:
            text = self.files.get((match.group(2), match.group(1)))
            if text is None:
                return None
            import base64
            return {"type": "file", "content": base64.b64encode(text.encode()).decode()}
        if path.startswith(consumer + "/pulls?state=open"):
            assert "head=box1-org%3Abundle/site-gateway" in path and "base=" not in path, path
            return self.prs
        if path == consumer + "/git/ref/heads/bundle/site-gateway":
            return {"object": {"sha": "old"}} if self.branch_exists else None
        if path == consumer + "/git/commits/old":
            return {"message": self.branch_tip}
        if path == consumer + "/git/commits/main-sha":
            return {"tree": {"sha": "tree-main"}}
        if path.endswith("/merge"):
            raise AssertionError("the consumer PR must never be merged")
        if method == "POST" and path.endswith("/git/blobs"):
            self.blob = body["content"]
            return {"sha": "blob-1"}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": "tree-1"}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": "commit-1"}
        if method in ("POST", "PATCH") and "/git/refs" in path:
            return {}
        if method == "POST" and path.endswith("/pulls"):
            return {"number": 7, "html_url": "https://github.com/box1-org/site-gateway-os/pull/7"}
        if method == "PATCH" and "/pulls/" in path:
            return {"number": 5, "html_url": "https://github.com/box1-org/site-gateway-os/pull/5"}
        raise AssertionError("unexpected GitHub call %s %s" % (method, path))


def env(**overrides):
    values = {"REVISION": SOURCE_SHA, "IMAGE_DIGEST": NEW, "BUNDLE_NAME": "site-gateway-bundle", "SOURCE_REPOSITORY": "box1-org/site-gateway",
              "CONSUMER_REPOSITORY": "site-gateway-os", "CONSUMER_PATH": "Containerfile", "GATE_POLICY": "pass", "PIPELINE_RUN": "site-gateway-release-x"}
    values.update(overrides)
    return values


def our_pr(head_sha="pr-head"):
    return {"number": 5, "html_url": "https://github.com/box1-org/site-gateway-os/pull/5", "base": {"ref": "main"}, "head": {"sha": head_sha, "repo": {"full_name": "box1-org/site-gateway-os"}},
            "body": "old\n<!-- box1-bundle-source: box1-org/site-gateway -->\n"}


class ConsumerPullRequestTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script, cls.ns = load(CONSUMER_TASK, "propose")

    def run_propose(self, api, **overrides):
        results = {}
        outcome = self.ns["propose"](env(**overrides), api, lambda k, v: results.__setitem__(k, v))
        return outcome, results

    def test_rewrite_changes_exactly_one_line_and_only_the_digest(self):
        new, old = self.ns["rewrite"](CONTAINERFILE, "site-gateway-bundle", NEW)
        self.assertEqual(old, "sha256:" + "0" * 64)
        changed = [(a, b) for a, b in zip(CONTAINERFILE.split("\n"), new.split("\n")) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][1], "COPY --from=registry.apps.ocp.box1.org/box1-ci/site-gateway-bundle@%s / /usr/lib/site-gateway/" % NEW)
        self.assertIn("site-gateway-bundle2@sha256:" + "d" * 64, new, "a longer bundle name is a different bundle")

    def test_crlf_and_extra_flags_are_preserved(self):
        text = "FROM x\r\nCOPY --chown=0:0 --from=image-registry.openshift-image-registry.svc:5000/box1-ci/site-gateway-bundle@sha256:%s / /opt/sg/\r\n" % ("0" * 64)
        new, _ = self.ns["rewrite"](text, "site-gateway-bundle", NEW)
        self.assertEqual(new, text.replace("sha256:" + "0" * 64, NEW))

    def test_zero_or_two_copy_lines_fail_clearly(self):
        rewrite = self.ns["rewrite"]
        with self.assertRaises(SystemExit) as zero:
            rewrite("FROM x\nCOPY app /app\n", "site-gateway-bundle", NEW, "Containerfile")
        self.assertIn("exactly one COPY --from=.../box1-ci/site-gateway-bundle@sha256:<digest> line; found 0. Nothing was proposed.", str(zero.exception))
        line = "COPY --from=r/box1-ci/site-gateway-bundle@sha256:%s / /x/\n" % ("0" * 64)
        with self.assertRaises(SystemExit) as two:
            rewrite("FROM x\n" + line + line, "site-gateway-bundle", NEW, "Containerfile")
        self.assertIn("found 2 (lines 2, 3)", str(two.exception))
        with self.assertRaises(SystemExit) as alias:
            rewrite("FROM r/box1-ci/site-gateway-bundle@sha256:%s AS bundle\nCOPY --from=bundle / /x/\n" % ("0" * 64), "site-gateway-bundle", NEW)
        self.assertIn("other references on lines 1 (FROM stage aliases are not supported)", str(alias.exception))
        with self.assertRaises(SystemExit) as tag:
            rewrite("COPY --from=r/box1-ci/site-gateway-bundle:latest / /x/\n", "site-gateway-bundle", NEW)
        self.assertIn("must pin box1-ci/site-gateway-bundle by digest", str(tag.exception))

    def test_another_reference_to_the_bundle_fails_even_with_one_copy_line(self):
        text = CONTAINERFILE + "FROM r/box1-ci/site-gateway-bundle@sha256:%s AS old\n" % ("0" * 64)
        with self.assertRaises(SystemExit) as raised:
            self.ns["rewrite"](text, "site-gateway-bundle", NEW)
        self.assertIn("found 1 (lines 3); other references on lines 6", str(raised.exception))

    def test_a_leftover_branch_is_reused_only_if_its_tip_is_a_bump_commit(self):
        api = FakeGitHub(branch_exists=True)
        self.assertEqual(self.run_propose(api)[0], "opened")
        self.assertIn(("PATCH", "/repos/box1-org/site-gateway-os/git/refs/heads/bundle/site-gateway", {"sha": "commit-1", "force": True}), api.writes)
        foreign = FakeGitHub(branch_exists=True, branch_tip="my manual work")
        with self.assertRaises(SystemExit) as raised:
            self.run_propose(foreign)
        self.assertIn("its tip is not a bump commit of this automation", str(raised.exception))
        self.assertFalse(any("/git/refs" in w[1] or w[1].endswith("/pulls") for w in foreign.writes))

    def test_an_open_bump_pr_against_another_base_is_refused(self):
        other = our_pr()
        other["base"] = {"ref": "release"}
        with self.assertRaises(SystemExit):
            self.run_propose(FakeGitHub(open_prs=[other], branch_exists=True))

    def test_a_bad_consumer_file_writes_nothing(self):
        api = FakeGitHub(files={("main-sha", "Containerfile"): "FROM x\n"})
        with self.assertRaises(SystemExit):
            self.run_propose(api)
        self.assertEqual(api.writes, [])

    def test_gate_failure_proposes_nothing_and_calls_nothing(self):
        for policy in ["fail", "disabled", "", "unavailable"]:
            api = FakeGitHub()
            with self.assertRaises(SystemExit) as raised:
                self.run_propose(api, GATE_POLICY=policy)
            self.assertIn("a bundle that fails policy is never proposed", str(raised.exception))
            self.assertEqual(api.calls, [])

    def test_unsafe_inputs_are_rejected_before_any_call(self):
        for overrides in [{"CONSUMER_REPOSITORY": "box1-gitops"}, {"CONSUMER_REPOSITORY": "box1-workloads-dev"}, {"CONSUMER_REPOSITORY": "site-gateway"},
                          {"CONSUMER_REPOSITORY": "other-org/x"}, {"CONSUMER_PATH": "../Containerfile"}, {"CONSUMER_PATH": "/etc/x"},
                          {"CONSUMER_PATH": "a/./b"}, {"BUNDLE_NAME": "other-bundle"}, {"IMAGE_DIGEST": "sha256:abc"}, {"REVISION": "main"},
                          {"SOURCE_REPOSITORY": "elsewhere/site-gateway"}]:
            api = FakeGitHub()
            with self.assertRaises(SystemExit, msg=str(overrides)):
                self.run_propose(api, **overrides)
            self.assertEqual(api.calls, [], overrides)

    def test_new_bump_opens_one_pr_with_a_one_line_change_and_never_merges(self):
        api = FakeGitHub()
        outcome, results = self.run_propose(api)
        self.assertEqual(outcome, "opened")
        self.assertEqual(results, {"outcome": "opened", "pr-url": "https://github.com/box1-org/site-gateway-os/pull/7"})
        self.assertEqual(api.blob, self.ns["rewrite"](CONTAINERFILE, "site-gateway-bundle", NEW)[0])
        posts = [w for w in api.writes if w[1].endswith("/pulls")]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]["head"], "bundle/site-gateway")
        self.assertIn("<!-- box1-bundle-source: box1-org/site-gateway -->", posts[0][2]["body"])
        self.assertIn(("POST", "/repos/box1-org/site-gateway-os/git/refs", {"ref": "refs/heads/bundle/site-gateway", "sha": "commit-1"}), api.writes)
        self.assertFalse(any(w[1].endswith("/merge") for w in api.writes))

    def test_an_open_pr_for_an_older_digest_is_updated_not_duplicated(self):
        api = FakeGitHub(open_prs=[our_pr()], branch_exists=True,
                         files={("pr-head", "Containerfile"): CONTAINERFILE.replace("0" * 64, "9" * 64, 1)})
        outcome, results = self.run_propose(api)
        self.assertEqual(outcome, "updated")
        self.assertEqual(results["pr-url"], "https://github.com/box1-org/site-gateway-os/pull/5")
        self.assertFalse(any(w[1].endswith("/pulls") and w[0] == "POST" for w in api.writes), "no second PR")
        self.assertIn(("PATCH", "/repos/box1-org/site-gateway-os/git/refs/heads/bundle/site-gateway", {"sha": "commit-1", "force": True}), api.writes)

    def test_a_rerun_of_the_same_revision_is_idempotent(self):
        proposed = self.ns["rewrite"](CONTAINERFILE, "site-gateway-bundle", NEW)[0]
        api = FakeGitHub(open_prs=[our_pr()], branch_exists=True, files={("pr-head", "Containerfile"): proposed})
        outcome, results = self.run_propose(api)
        self.assertEqual((outcome, results["pr-url"]), ("unchanged", "https://github.com/box1-org/site-gateway-os/pull/5"))
        self.assertEqual(api.writes, [])

    def test_a_consumer_already_pinning_the_digest_gets_no_pr_and_stale_ones_close(self):
        pinned = CONTAINERFILE.replace("sha256:" + "0" * 64, NEW, 1)
        api = FakeGitHub(files={("main-sha", "Containerfile"): pinned})
        self.assertEqual(self.run_propose(api), ("current", {"outcome": "current", "pr-url": "current"}))
        self.assertEqual(api.writes, [])
        stale = FakeGitHub(files={("main-sha", "Containerfile"): pinned}, open_prs=[our_pr()])
        self.assertEqual(self.run_propose(stale)[0], "current")
        self.assertEqual(stale.writes, [("PATCH", "/repos/box1-org/site-gateway-os/pulls/5", {"state": "closed"})])

    def test_a_superseded_revision_proposes_nothing(self):
        api = FakeGitHub(source_main=BUNDLE_SHA)
        self.assertEqual(self.run_propose(api), ("superseded", {"outcome": "superseded", "pr-url": "superseded"}))
        self.assertEqual(api.writes, [])

    def test_a_foreign_pr_on_the_branch_is_not_touched(self):
        foreign = our_pr()
        foreign["body"] = "someone else's change"
        api = FakeGitHub(open_prs=[foreign], branch_exists=True)
        with self.assertRaises(SystemExit) as raised:
            self.run_propose(api)
        self.assertIn("was not opened by this automation", str(raised.exception))
        self.assertEqual(api.writes, [])
        fork = our_pr()
        fork["head"]["repo"] = {"full_name": "someone/site-gateway-os"}
        with self.assertRaises(SystemExit):
            self.run_propose(FakeGitHub(open_prs=[fork], branch_exists=True))

    def test_missing_consumer_or_file_fails_clearly(self):
        with self.assertRaises(SystemExit) as repo:
            self.run_propose(FakeGitHub(consumer_exists=False))
        self.assertIn("Consumer repository box1-org/site-gateway-os does not exist", str(repo.exception))
        with self.assertRaises(SystemExit) as file:
            self.run_propose(FakeGitHub(), CONSUMER_PATH="images/Containerfile")
        self.assertIn("has no file images/Containerfile on main", str(file.exception))

    def test_task_has_no_merge_call_and_reads_the_token_from_the_pipelinerun_secret(self):
        self.assertNotIn("/merge", self.script)
        task = CONSUMER_TASK.read_text()
        self.assertIn("name: \"$(params.git-auth-secret)\"", task)


class PlatformSettings(unittest.TestCase):
    """box1-docs#165: RHDP org and registry route come from box1-platform-settings; without it the homelab literals apply."""

    def push_image(self, settings=None):
        line = [l for l in step_script(BUNDLE_TASK, "push").splitlines() if l.startswith("image=")]
        self.assertEqual(len(line), 1)
        return subprocess.run(["sh", "-euc", line[0] + '\nprintf %s "$image"'], env=settings_env(settings) | {"IMAGE_NAME": "site-gateway-bundle"},
                              text=True, capture_output=True, check=True).stdout

    def source_label(self, ns, source):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / "application").mkdir()
            (work / "application" / "pom.xml").write_text(pom(["gateway"]))
            fast_jar(work / "application", "gateway")
            ns["stage"](work / "application", ["gateway"], work / "bundle")
            ns["make_layout"](work / "bundle", work / "oci", "a" * 40, source, ["gateway"])
            index = json.loads((work / "oci" / "index.json").read_text())
            digest = index["manifests"][0]["digest"].split(":")[1]
            manifest = json.loads((work / "oci" / "blobs" / "sha256" / digest).read_text())
            return manifest["annotations"]["org.opencontainers.image.source"]

    def test_steps_read_the_optional_settings_configmap(self):
        self.assertEqual(BUNDLE_TASK.read_text().count(ENVFROM), 3)
        self.assertEqual(CONSUMER_TASK.read_text().count(ENVFROM), 1)
        self.assertEqual(QUARKUS_MAVEN.read_text().count(ENVFROM), 2)
        quarkus = QUARKUS_MAVEN.read_text()
        self.assertIn("repo=os.environ['SOURCE_REPO'] or org+'/quarkus-reference'", quarkus)
        self.assertIn('-Dquarkus.container-image.registry="${BOX1_REGISTRY_HOST:-registry.apps.ocp.box1.org}"', quarkus)

    def test_homelab_defaults_without_the_configmap(self):
        _, bundle = load(BUNDLE_TASK, "verify-and-package")
        self.assertEqual(self.source_label(bundle, "box1-org/site-gateway"), "https://github.com/box1-org/site-gateway")
        self.assertEqual(self.push_image(), "registry.apps.ocp.box1.org/box1-ci/site-gateway-bundle")
        _, consumer = load(CONSUMER_TASK, "propose")
        self.assertEqual((consumer["ORG"], consumer["PROTECTED"]), ("box1-org", ("box1-gitops", "box1-workloads-dev")))

    def test_rhdp_org_and_registry_route_come_from_the_configmap(self):
        _, bundle = load(BUNDLE_TASK, "verify-and-package", RHDP_SETTINGS)
        self.assertEqual(bundle["GIT_ORG"], "box1-rhdp")
        self.assertEqual(self.source_label(bundle, "box1-rhdp/site-gateway"), "https://github.com/box1-rhdp/site-gateway")
        self.assertEqual(self.push_image(RHDP_SETTINGS), RHDP_SETTINGS["BOX1_REGISTRY_HOST"] + "/box1-ci/site-gateway-bundle")
        _, consumer = load(CONSUMER_TASK, "propose", RHDP_SETTINGS)
        rhdp = env(SOURCE_REPOSITORY="box1-rhdp/site-gateway")
        self.assertEqual(consumer["check_inputs"](rhdp)[2:4], ("box1-rhdp/site-gateway", "site-gateway"))
        with self.assertRaisesRegex(SystemExit, "Source repository must be box1-rhdp/<name>"):
            consumer["check_inputs"](env())
        for protected in ["box1-gitops", "box1-workloads-dev"]:
            with self.assertRaisesRegex(SystemExit, "never box1-gitops or box1-workloads-dev"):
                consumer["check_inputs"](env(SOURCE_REPOSITORY="box1-rhdp/site-gateway", CONSUMER_REPOSITORY=protected))


if __name__ == "__main__":
    unittest.main()
