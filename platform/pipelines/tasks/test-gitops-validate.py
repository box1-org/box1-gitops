#!/usr/bin/env python3
"""Contract tests for the workload profiles in box1-gitops-validate.

The validation functions are loaded from the Task's embedded script and run
against bundles rendered with a real `kubectl kustomize` (or `oc kustomize`),
so list and key ordering match what the Task sees.

Optional regression check against live service workloads:
  BOX1_WORKLOADS_DEV=/path/to/box1-workloads-dev python3 test-gitops-validate.py
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).parent
TASK = ROOT / "gitops-validate.yaml"
ZERO = "sha256:" + "0" * 64
OS_DIGEST = "sha256:" + "a" * 64
DISK_DIGEST = "sha256:" + "b" * 64
SOURCE = "c" * 40
KUSTOMIZE = shutil.which("kubectl") or shutil.which("oc")


def load_validator():
    text = TASK.read_text()
    start = text.index("    script: |")
    body = []
    for line in text[start:].splitlines()[1:]:
        if line and not line.startswith("      "):
            break
        body.append(line[6:] if line else "")
    namespace = {"__name__": "box1_gitops_validate"}
    exec(compile("\n".join(body), str(TASK), "exec"), namespace)
    return namespace


def vm_bundle(name="vm-fixture", promoted=False, **overrides):
    ns = name + "-dev"
    os_digest = OS_DIGEST if promoted else ZERO
    disk_digest = DISK_DIGEST if promoted else ZERO
    files = {
        "namespace.yaml": f"""
            apiVersion: v1
            kind: Namespace
            metadata:
              name: {ns}
              labels:
                argocd.argoproj.io/managed-by: openshift-gitops
                box1.org/workload-profile: virtual-machine
        """,
        "updater.yaml": f"""
            apiVersion: v1
            kind: ServiceAccount
            metadata:
              name: {name}-updater
              namespace: {ns}
            automountServiceAccountToken: false
            ---
            apiVersion: v1
            kind: Secret
            metadata:
              name: {name}-updater-token
              namespace: {ns}
              annotations:
                kubernetes.io/service-account.name: {name}-updater
            type: kubernetes.io/service-account-token
        """,
        "admin-access.yaml": f"""
            apiVersion: v1
            kind: Secret
            metadata:
              name: {name}-admin-ssh
              namespace: {ns}
            type: Opaque
            stringData:
              key1: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureFixtureFixtureFixtureFixtureFixture admin@example
        """,
        "virtualmachine.yaml": f"""
            apiVersion: kubevirt.io/v1
            kind: VirtualMachine
            metadata:
              name: {name}
              namespace: {ns}
              annotations:
                box1.org/os-image-digest: {os_digest}
                box1.org/source-revision: {SOURCE}
                box1.org/build-pipelinerun: awaiting-first-release
            spec:
              runStrategy: {"Always" if promoted else "Halted"}
              template:
                spec:
                  accessCredentials:
                    - sshPublicKey:
                        source:
                          secret:
                            secretName: {name}-admin-ssh
                        propagationMethod:
                          qemuGuestAgent:
                            users: [cloud-user]
                  domain:
                    devices:
                      disks:
                        - name: root
                          disk: {{bus: virtio}}
                        - name: serviceca
                          serial: serviceca
                          disk: {{bus: virtio}}
                        - name: regtoken
                          serial: regtoken
                          disk: {{bus: virtio}}
                  volumes:
                    - name: root
                      dataVolume:
                        name: {name}-root
                    - name: serviceca
                      configMap:
                        name: openshift-service-ca.crt
                    - name: regtoken
                      secret:
                        secretName: {name}-updater-token
        """,
        "datavolume.yaml": f"""
            apiVersion: cdi.kubevirt.io/v1beta1
            kind: DataVolume
            metadata:
              name: {name}-root
              namespace: {ns}
            spec:
              source:
                registry:
                  url: docker://image-registry.openshift-image-registry.svc:5000/box1-ci/{name}-disk@{disk_digest}
                  pullMethod: node
              storage:
                resources:
                  requests:
                    storage: 12Gi
        """,
    }
    resources = ["namespace.yaml", "updater.yaml", "admin-access.yaml", "virtualmachine.yaml"]
    if promoted:
        resources.append("datavolume.yaml")
    files.update(overrides.pop("files", {}))
    resources = overrides.pop("resources", resources)
    files["kustomization.yaml"] = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n" + "".join(
        f"  - {r}\n" for r in resources
    )
    return name, files


def render(files):
    with tempfile.TemporaryDirectory() as tmp:
        for path, content in files.items():
            (pathlib.Path(tmp) / path).write_text(textwrap.dedent(content).lstrip())
        return subprocess.check_output([KUSTOMIZE, "kustomize", tmp], text=True)


@unittest.skipUnless(KUSTOMIZE, "kubectl or oc is required to render fixtures")
class VirtualMachineProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = load_validator()

    def check(self, name, files):
        return self.v["validate"](name, render(files))

    def rejects(self, message, **kwargs):
        name, files = vm_bundle(**kwargs)
        with self.assertRaises(AssertionError) as raised:
            self.check(name, files)
        self.assertIn(message, str(raised.exception))

    def test_unbuilt_vm_bundle_is_accepted(self):
        self.assertEqual(self.check(*vm_bundle()), "virtual-machine")

    def test_promoted_vm_bundle_is_accepted(self):
        self.assertEqual(self.check(*vm_bundle(promoted=True)), "virtual-machine")

    def test_unbuilt_vm_must_not_create_its_datavolume(self):
        name, files = vm_bundle()
        files["kustomization.yaml"] += "  - datavolume.yaml\n"
        with self.assertRaisesRegex(AssertionError, "must not create their DataVolume"):
            self.check(name, files)

    def test_unbuilt_vm_must_stay_halted(self):
        name, files = vm_bundle()
        files["virtualmachine.yaml"] = files["virtualmachine.yaml"].replace("runStrategy: Halted", "runStrategy: Always")
        with self.assertRaisesRegex(AssertionError, "must stay Halted"):
            self.check(name, files)

    def test_promoted_vm_disk_must_be_digest_pinned_to_its_disk_image(self):
        name, files = vm_bundle(promoted=True)
        for bad in [f"{name}-disk:latest", f"other-disk@{DISK_DIGEST}", f"{name}-disk@{ZERO}"]:
            broken = dict(files)
            broken["datavolume.yaml"] = files["datavolume.yaml"].replace(f"{name}-disk@{DISK_DIGEST}", bad)
            with self.assertRaisesRegex(AssertionError, "digest-pinned"):
                self.check(name, broken)

    def test_promoted_vm_needs_its_datavolume(self):
        self.rejects("exactly one root DataVolume", promoted=True,
                     resources=["namespace.yaml", "updater.yaml", "admin-access.yaml", "virtualmachine.yaml"])

    def test_datavolume_templates_are_rejected(self):
        name, files = vm_bundle()
        files["virtualmachine.yaml"] = files["virtualmachine.yaml"].replace(
            "runStrategy: Halted", "runStrategy: Halted\n              dataVolumeTemplates: []")
        with self.assertRaisesRegex(AssertionError, "dataVolumeTemplates"):
            self.check(name, files)

    def test_update_disks_are_required(self):
        name, files = vm_bundle()
        files["virtualmachine.yaml"] = files["virtualmachine.yaml"].replace("serial: regtoken", "serial: other")
        with self.assertRaisesRegex(AssertionError, "regtoken"):
            self.check(name, files)

    def test_container_workloads_are_rejected_in_vm_profile(self):
        name, files = vm_bundle(files={"extra.yaml": """
            apiVersion: apps/v1
            kind: Deployment
            metadata: {name: sneaky, namespace: vm-fixture-dev}
            spec:
              selector: {matchLabels: {app: sneaky}}
              template:
                metadata: {labels: {app: sneaky}}
                spec: {containers: [{name: c, image: quay.io/evil/image:latest}]}
        """})
        files["kustomization.yaml"] += "  - extra.yaml\n"
        with self.assertRaisesRegex(AssertionError, "must not include Deployment"):
            self.check(name, files)

    def test_token_secret_must_not_carry_data(self):
        name, files = vm_bundle()
        files["updater.yaml"] = files["updater.yaml"].rstrip() + "\n            data:\n              token: c2VjcmV0\n"
        with self.assertRaisesRegex(AssertionError, "must not carry data"):
            self.check(name, files)

    def test_only_ssh_public_keys_may_be_stored(self):
        name, files = vm_bundle()
        files["admin-access.yaml"] = files["admin-access.yaml"].replace(
            "key1: ssh-ed25519", "password: hunter2 ssh-ed25519")
        with self.assertRaisesRegex(AssertionError, "Only SSH public keys"):
            self.check(name, files)

    def test_missing_os_digest_annotation_is_rejected(self):
        name, files = vm_bundle()
        files["virtualmachine.yaml"] = files["virtualmachine.yaml"].replace("box1.org/os-image-digest", "box1.org/other")
        with self.assertRaisesRegex(AssertionError, "os-image-digest"):
            self.check(name, files)

    def test_unknown_profile_is_rejected(self):
        name, files = vm_bundle()
        files["namespace.yaml"] = files["namespace.yaml"].replace("virtual-machine", "mainframe")
        with self.assertRaisesRegex(AssertionError, "Unknown workload profile"):
            self.check(name, files)


@unittest.skipUnless(KUSTOMIZE and os.environ.get("BOX1_WORKLOADS_DEV"), "set BOX1_WORKLOADS_DEV to a box1-workloads-dev checkout")
class ServiceProfileRegression(unittest.TestCase):
    def test_existing_service_workloads_still_validate(self):
        v = load_validator()
        targets = sorted(pathlib.Path(os.environ["BOX1_WORKLOADS_DEV"], "workloads").glob("*/kustomization.yaml"))
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(workload=target.parent.name):
                rendered = subprocess.check_output([KUSTOMIZE, "kustomize", str(target.parent)], text=True)
                self.assertEqual(v["validate"](target.parent.name, rendered), "service")


if __name__ == "__main__":
    unittest.main()
