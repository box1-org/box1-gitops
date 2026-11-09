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
import re
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


SOURCE_IMAGE = "site-gateway-os"


def instance_bundle(name="site-west", source=SOURCE_IMAGE, promoted=False, **overrides):
    """A `vm-instance` bundle: one instance of a shared bootc OS image (box1-docs#139, #140).

    The instance pins its own digests, takes its identity from a cloud-init NoCloud
    Secret created outside Git, and keeps non-secret site settings in a ConfigMap.
    """
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
                box1.org/workload-profile: vm-instance
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
        "site.yaml": f"""
            apiVersion: v1
            kind: ConfigMap
            metadata:
              name: {name}-site
              namespace: {ns}
            data:
              siteId: site_ds9
              gatewayUrl: https://gateway.example.test
              keycloakUrl: https://sso.example.test/realms/box1
              keycloakClientId: {name}-gateway
        """,
        "virtualmachine.yaml": f"""
            apiVersion: kubevirt.io/v1
            kind: VirtualMachine
            metadata:
              name: {name}
              namespace: {ns}
              annotations:
                box1.org/source-image: {source}
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
                        - name: cloudinitdisk
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
                    - name: cloudinitdisk
                      cloudInitNoCloud:
                        secretRef:
                          name: {name}-cloud-init
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
                  url: docker://image-registry.openshift-image-registry.svc:5000/box1-ci/{source}-disk@{disk_digest}
                  pullMethod: node
              storage:
                resources:
                  requests:
                    storage: 12Gi
        """,
    }
    resources = ["namespace.yaml", "updater.yaml", "admin-access.yaml", "site.yaml", "virtualmachine.yaml"]
    if promoted:
        resources.append("datavolume.yaml")
    files.update(overrides.pop("files", {}))
    resources = overrides.pop("resources", resources)
    files["kustomization.yaml"] = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n" + "".join(
        f"  - {r}\n" for r in resources
    )
    return name, files


def edit(files, path, old, new):
    changed = dict(files)
    assert old in changed[path], (path, old)
    changed[path] = changed[path].replace(old, new)
    return changed


@unittest.skipUnless(KUSTOMIZE, "kubectl or oc is required to render fixtures")
class VmInstanceProfile(unittest.TestCase):
    """box1-docs#139: many instances of one bootc OS image, each pinning its own digest."""

    @classmethod
    def setUpClass(cls):
        cls.v = load_validator()

    def check(self, name, files):
        return self.v["validate"](name, render(files))

    def rejects(self, message, name, files):
        with self.assertRaises(AssertionError) as raised:
            self.check(name, files)
        self.assertIn(message, str(raised.exception))
        return str(raised.exception)

    def test_profile_table_lists_exactly_the_supported_profiles(self):
        self.assertEqual(sorted(self.v["PROFILE_CHECKS"]), ["service", "virtual-machine", "vm-instance"])

    def test_allowlist_lives_in_the_validator_task(self):
        self.assertIn(SOURCE_IMAGE, self.v["VM_INSTANCE_SOURCES"])
        for source in self.v["VM_INSTANCE_SOURCES"]:
            self.assertRegex(source, r"^[a-z][a-z0-9-]{2,39}$")

    def test_unbuilt_instance_is_accepted(self):
        self.assertEqual(self.check(*instance_bundle()), "vm-instance")

    def test_promoted_instance_is_accepted(self):
        self.assertEqual(self.check(*instance_bundle(promoted=True)), "vm-instance")

    def test_two_instances_of_one_source_are_each_accepted(self):
        for instance in ["site-west", "site-east"]:
            self.assertEqual(self.check(*instance_bundle(instance, promoted=True)), "vm-instance")

    def test_vm_name_must_match_the_instance(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml", f"  name: {name}\n", "  name: site-other\n")
        message = self.rejects("VirtualMachine must be named after the instance site-west", name, files)
        self.assertIn("site-other", message)

    def test_tag_disk_is_rejected(self):
        name, files = instance_bundle(promoted=True)
        files = edit(files, "datavolume.yaml", f"{SOURCE_IMAGE}-disk@{DISK_DIGEST}", f"{SOURCE_IMAGE}-disk:latest")
        self.rejects("Root DataVolume must pull the digest-pinned site-gateway-os-disk image", name, files)

    def test_zero_disk_digest_is_rejected_once_promoted(self):
        name, files = instance_bundle(promoted=True)
        files = edit(files, "datavolume.yaml", f"{SOURCE_IMAGE}-disk@{DISK_DIGEST}", f"{SOURCE_IMAGE}-disk@{ZERO}")
        self.rejects("digest-pinned site-gateway-os-disk", name, files)

    def test_disk_from_another_source_is_rejected(self):
        name, files = instance_bundle(promoted=True)
        files = edit(files, "datavolume.yaml", f"{SOURCE_IMAGE}-disk@", f"legacy-erp-disk@")
        self.rejects("digest-pinned site-gateway-os-disk", name, files)

    def test_source_outside_the_allowlist_is_rejected(self):
        name, files = instance_bundle(source="rogue-os", promoted=True)
        self.rejects("Source image rogue-os is not on the vm-instance allowlist", name, files)

    def test_source_annotation_is_required(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml", "box1.org/source-image:", "box1.org/other-image:")
        self.rejects("box1.org/source-image", name, files)

    def test_zero_digest_while_always_is_rejected(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml", "runStrategy: Halted", "runStrategy: Always")
        self.rejects("Unbuilt virtual machines must stay Halted", name, files)

    def test_unbuilt_instance_must_not_create_its_datavolume(self):
        name, files = instance_bundle()
        files["kustomization.yaml"] += "  - datavolume.yaml\n"
        self.rejects("must not create their DataVolume", name, files)

    def test_datavolume_must_be_named_after_the_instance(self):
        name, files = instance_bundle(promoted=True)
        files = edit(files, "datavolume.yaml", f"  name: {name}-root\n", "  name: shared-root\n")
        self.rejects("Root DataVolume must be named site-west-root", name, files)

    def test_update_disks_follow_the_vm_rules(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml", "serial: serviceca", "serial: other")
        self.rejects("serviceca", name, files)

    def test_inline_cloud_init_data_is_rejected(self):
        for key in ["userData", "userDataBase64", "networkData", "networkDataBase64"]:
            with self.subTest(key=key):
                name, files = instance_bundle()
                files = edit(files, "virtualmachine.yaml", "                        secretRef:\n",
                             f"                        {key}: '#cloud-config'\n                        secretRef:\n")
                self.rejects("must not inline " + key, name, files)

    def test_inline_cloud_init_in_a_config_drive_is_rejected(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml", "cloudInitNoCloud:\n                        secretRef:\n",
                     "cloudInitConfigDrive:\n                        userData: '#cloud-config'\n                        secretRef:\n")
        self.rejects("must not inline userData", name, files)

    def test_cloud_init_volume_is_required(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml",
                     "                    - name: cloudinitdisk\n                      cloudInitNoCloud:\n"
                     "                        secretRef:\n                          name: site-west-cloud-init\n", "")
        self.rejects("exactly one cloudInitNoCloud volume", name, files)

    def test_cloud_init_secret_ref_must_name_the_instance_secret(self):
        name, files = instance_bundle()
        files = edit(files, "virtualmachine.yaml", "name: site-west-cloud-init", "name: site-east-cloud-init")
        self.rejects("secretRef.name: site-west-cloud-init", name, files)

    def test_cloud_init_secret_must_not_be_rendered_from_git(self):
        name, files = instance_bundle(files={"cloud-init.yaml": """
            apiVersion: v1
            kind: Secret
            metadata:
              name: site-west-cloud-init
              namespace: site-west-dev
            type: Opaque
        """})
        files["kustomization.yaml"] += "  - cloud-init.yaml\n"
        self.rejects("Secret site-west-cloud-init must be created outside Git", name, files)

    def test_secret_with_data_in_git_is_rejected(self):
        name, files = instance_bundle(files={"client.yaml": """
            apiVersion: v1
            kind: Secret
            metadata:
              name: site-west-client
              namespace: site-west-dev
            type: Opaque
            data:
              client-secret: c2VjcmV0
        """})
        files["kustomization.yaml"] += "  - client.yaml\n"
        self.rejects("Only SSH public keys may be stored in Secrets", name, files)

    def test_site_configmap_must_not_hold_credentials(self):
        for key in ["clientSecret", "password", "admin_password", "registry-token", "apiKey", "private.key", "KEYCLOAK_CLIENT_SECRET"]:
            with self.subTest(key=key):
                name, files = instance_bundle()
                files = edit(files, "site.yaml", "siteId: site_ds9", f"siteId: site_ds9\n              {key}: value")
                self.rejects("ConfigMap site-west-site must not hold credentials", name, files)

    def test_site_configmap_must_not_hold_a_private_key_value(self):
        name, files = instance_bundle()
        files = edit(files, "site.yaml", "siteId: site_ds9",
                     "siteId: site_ds9\n              bundle: |\n                -----BEGIN PRIVATE KEY-----\n                MIIE\n                -----END PRIVATE KEY-----")
        self.rejects("ConfigMap site-west-site must not hold credentials", name, files)

    def test_site_configmap_values_must_not_embed_credentials(self):
        # Review finding (box1-docs#139): credentials inside a file-shaped value.
        for value in ["gateway.yaml: |\n                admin_password: hunter2",
                      "settings.env: 'PASSWORD=hunter2'",
                      "client.properties: 'quarkus.oidc.credentials.secret = s3cr3t'",
                      "kubeconfig: placeholder"]:
            with self.subTest(value=value):
                name, files = instance_bundle()
                files = edit(files, "site.yaml", "siteId: site_ds9", "siteId: site_ds9\n              " + value)
                self.rejects("ConfigMap site-west-site must not hold credentials", name, files)

    def test_site_configmap_settings_are_accepted(self):
        # keycloakUrl and keycloakClientId contain "key" only inside the word "keycloak".
        name, files = instance_bundle()
        self.assertIn("keycloakClientId", files["site.yaml"])
        self.assertEqual(self.check(name, files), "vm-instance")

    def test_container_workloads_are_rejected(self):
        name, files = instance_bundle(files={"extra.yaml": """
            apiVersion: apps/v1
            kind: Deployment
            metadata: {name: sneaky, namespace: site-west-dev}
            spec:
              selector: {matchLabels: {app: sneaky}}
              template:
                metadata: {labels: {app: sneaky}}
                spec: {containers: [{name: c, image: quay.io/evil/image:latest}]}
        """})
        files["kustomization.yaml"] += "  - extra.yaml\n"
        self.rejects("must not include Deployment", name, files)

    def test_virtual_machine_profile_ignores_instance_rules(self):
        # The existing profile is unchanged: no source annotation, cloud-init or allowlist needed.
        self.assertEqual(self.check(*vm_bundle(promoted=True)), "virtual-machine")


def ci_bundle(repo="site-gateway", **overrides):
    """A `ci/<repo>/` bundle for a code-only (`artifact` profile) repository (box1-docs#137)."""
    files = {
        "repository.yaml": f"""
            apiVersion: pipelinesascode.tekton.dev/v1alpha1
            kind: Repository
            metadata:
              name: {repo}
              namespace: box1-ci
            spec:
              url: https://github.com/box1-org/{repo}
              concurrency_limit: 1
              settings:
                pipelinerun_provenance: default_branch
                github_app_token_scope_repos:
                - box1-org/site-gateway-os
        """,
        "release.yaml": f"""
            apiVersion: v1
            kind: ServiceAccount
            metadata:
              name: {repo}-release
              namespace: box1-ci
            ---
            apiVersion: image.openshift.io/v1
            kind: ImageStream
            metadata:
              name: {repo}-bundle
              namespace: box1-ci
            spec:
              lookupPolicy:
                local: false
            ---
            apiVersion: rbac.authorization.k8s.io/v1
            kind: Role
            metadata:
              name: {repo}-bundle-push
              namespace: box1-ci
            rules:
              - apiGroups: ["", "image.openshift.io"]
                resources: ["imagestreams/layers"]
                resourceNames: ["{repo}-bundle"]
                verbs: ["get", "update"]
            ---
            apiVersion: rbac.authorization.k8s.io/v1
            kind: RoleBinding
            metadata:
              name: {repo}-bundle-push
              namespace: box1-ci
            roleRef:
              apiGroup: rbac.authorization.k8s.io
              kind: Role
              name: {repo}-bundle-push
            subjects:
              - kind: ServiceAccount
                name: {repo}-release
                namespace: box1-ci
        """,
        "observer.yaml": f"""
            apiVersion: rbac.authorization.k8s.io/v1
            kind: Role
            metadata:
              name: {repo}-release-observer
              namespace: box1-ci
            rules:
              - apiGroups: [image.openshift.io]
                resources: [imagestreams, imagestreamtags]
                resourceNames: ["{repo}-bundle"]
                verbs: [get]
              - apiGroups: [pipelinesascode.tekton.dev]
                resources: [repositories]
                resourceNames: ["{repo}"]
                verbs: [get]
            ---
            apiVersion: rbac.authorization.k8s.io/v1
            kind: RoleBinding
            metadata:
              name: {repo}-release-observer
              namespace: box1-ci
            roleRef:
              apiGroup: rbac.authorization.k8s.io
              kind: Role
              name: {repo}-release-observer
            subjects:
              - kind: ServiceAccount
                name: ci-observe
                namespace: box1-ci
        """,
    }
    resources = ["repository.yaml", "release.yaml", "observer.yaml"]
    files.update(overrides.pop("files", {}))
    resources = overrides.pop("resources", resources)
    files["kustomization.yaml"] = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n" + "".join(
        f"  - {r}\n" for r in resources
    )
    return repo, files


@unittest.skipUnless(KUSTOMIZE, "kubectl or oc is required to render fixtures")
class CiBundle(unittest.TestCase):
    """box1-docs#137/#139: `ci/<repo>/` holds only the PaC Repository and its scoped box1-ci RBAC."""

    @classmethod
    def setUpClass(cls):
        cls.v = load_validator()

    def check(self, repo, files):
        return self.v["check_ci"](repo, render(files))

    def rejects(self, message, repo, files):
        with self.assertRaises(AssertionError) as raised:
            self.check(repo, files)
        self.assertIn(message, str(raised.exception))

    def extra(self, text, repo="site-gateway"):
        repo, files = ci_bundle(repo, files={"extra.yaml": text})
        files["kustomization.yaml"] += "  - extra.yaml\n"
        return repo, files

    def test_valid_ci_bundle_is_accepted(self):
        self.check(*ci_bundle())

    def test_repository_only_bundle_is_accepted(self):
        self.check(*ci_bundle(resources=["repository.yaml"]))

    def test_deployment_is_rejected(self):
        self.rejects("CI bundle ci/site-gateway may contain only", *self.extra("""
            apiVersion: apps/v1
            kind: Deployment
            metadata: {name: site-gateway, namespace: box1-ci}
            spec:
              selector: {matchLabels: {app: g}}
              template:
                metadata: {labels: {app: g}}
                spec: {containers: [{name: c, image: quay.io/x/y:1}]}
        """))

    def test_namespace_is_rejected(self):
        self.rejects("found Namespace site-gateway-dev", *self.extra("""
            apiVersion: v1
            kind: Namespace
            metadata: {name: site-gateway-dev}
        """))

    def test_secret_is_rejected(self):
        self.rejects("found Secret site-gateway-token", *self.extra("""
            apiVersion: v1
            kind: Secret
            metadata: {name: site-gateway-token, namespace: box1-ci}
            stringData: {token: value}
        """))

    def test_resources_outside_box1_ci_are_rejected(self):
        self.rejects("must be in namespace box1-ci: Role/site-gateway-argo", *self.extra("""
            apiVersion: rbac.authorization.k8s.io/v1
            kind: Role
            metadata: {name: site-gateway-argo, namespace: openshift-gitops}
            rules:
              - apiGroups: [argoproj.io]
                resources: [applications]
                resourceNames: [site-gateway-ci]
                verbs: [get]
        """))

    def test_kind_from_another_api_group_is_rejected(self):
        self.rejects("apiVersion", *self.extra("""
            apiVersion: example.com/v1
            kind: Role
            metadata: {name: site-gateway-fake, namespace: box1-ci}
        """))

    def test_exactly_one_repository_named_after_the_directory(self):
        self.rejects("exactly one PaC Repository named site-gateway", *ci_bundle(resources=["release.yaml"]))
        repo, files = ci_bundle()
        self.rejects("exactly one PaC Repository named other-repo", "other-repo", files)

    def test_repository_must_point_at_its_github_repository(self):
        repo, files = ci_bundle()
        files = edit(files, "repository.yaml", "url: https://github.com/box1-org/site-gateway", "url: https://github.com/evil/site-gateway")
        self.rejects("must point at https://github.com/box1-org/site-gateway", repo, files)

    def test_repository_must_use_default_branch_provenance(self):
        repo, files = ci_bundle()
        files = edit(files, "repository.yaml", "pipelinerun_provenance: default_branch", "pipelinerun_provenance: source")
        self.rejects("pipelinerun_provenance: default_branch", repo, files)

    def test_repository_token_scope_excludes_the_gitops_repositories(self):
        for scope in ["box1-org/box1-gitops", "box1-org/box1-workloads-dev", "other-org/site-gateway-os"]:
            with self.subTest(scope=scope):
                repo, files = ci_bundle()
                files = edit(files, "repository.yaml", "- box1-org/site-gateway-os", "- " + scope)
                self.rejects("github_app_token_scope_repos", repo, files)

    def test_repository_settings_are_read_from_settings_only(self):
        # Review finding (box1-docs#139): decoy keys under another map must not satisfy the check.
        repo, files = ci_bundle()
        files = edit(files, "repository.yaml", "              settings:\n",
                     "              git_provider:\n                pipelinerun_provenance: default_branch\n              settings:\n")
        files = edit(files, "repository.yaml", "pipelinerun_provenance: default_branch\n                github_app",
                     "pipelinerun_provenance: source\n                github_app")
        self.rejects("PaC Repository site-gateway spec may set only", repo, files)

    def test_repository_spec_and_settings_keys_are_allowlisted(self):
        for old, new, message in [
            ("concurrency_limit: 1", "concurrency_limit: 1\n              params:\n              - name: x\n                secret_ref: {name: box1-gitops-token, key: token}", "spec may set only"),
            ("concurrency_limit: 1", "concurrency_limit: 1\n              git_provider: {url: https://evil.example.com, secret: {name: box1-gitops-token}}", "spec may set only"),
            ("pipelinerun_provenance: default_branch", "pipelinerun_provenance: default_branch\n                policy: {ok_to_test: [mallory]}", "settings may set only"),
        ]:
            with self.subTest(new=new):
                repo, files = ci_bundle()
                self.rejects(message, repo, edit(files, "repository.yaml", old, new))

    def test_role_resources_exclude_wildcard_and_proxy_subresources(self):
        for resource in ["'*/status'", "pods/exec", "pods/attach", "services/proxy", "pods/portforward", "serviceaccounts/token"]:
            with self.subTest(resource=resource):
                self.rejects("Role site-gateway-sub", *self.extra(f"""
                    apiVersion: rbac.authorization.k8s.io/v1
                    kind: Role
                    metadata: {{name: site-gateway-sub, namespace: box1-ci}}
                    rules:
                      - apiGroups: ['']
                        resources: [{resource}]
                        resourceNames: [site-gateway]
                        verbs: [get]
                """))

    def test_imagestream_must_be_the_bundle_stream(self):
        repo, files = ci_bundle()
        files = edit(files, "release.yaml", "  name: site-gateway-bundle\n", "  name: box1-ops-erp-simulator\n")
        self.rejects("ImageStream must be named site-gateway-bundle", repo, files)

    def test_names_must_carry_the_repository_prefix(self):
        self.rejects("must be named site-gateway-", *self.extra("""
            apiVersion: v1
            kind: ServiceAccount
            metadata: {name: ci-gitops, namespace: box1-ci}
        """))

    def test_wildcard_role_is_rejected(self):
        self.rejects("Role site-gateway-wild", *self.extra("""
            apiVersion: rbac.authorization.k8s.io/v1
            kind: Role
            metadata: {name: site-gateway-wild, namespace: box1-ci}
            rules:
              - apiGroups: ['*']
                resources: ['*']
                resourceNames: [site-gateway]
                verbs: ['*']
        """))

    def test_role_without_resource_names_is_rejected(self):
        self.rejects("must name its resources", *self.extra("""
            apiVersion: rbac.authorization.k8s.io/v1
            kind: Role
            metadata: {name: site-gateway-list, namespace: box1-ci}
            rules:
              - apiGroups: [tekton.dev]
                resources: [pipelineruns]
                verbs: [get, list]
        """))

    def test_role_on_secrets_is_rejected(self):
        self.rejects("must not grant access to Secrets", *self.extra("""
            apiVersion: rbac.authorization.k8s.io/v1
            kind: Role
            metadata: {name: site-gateway-secrets, namespace: box1-ci}
            rules:
              - apiGroups: ['']
                resources: [secrets]
                resourceNames: [ci-gitops-token]
                verbs: [get]
        """))

    def test_write_verbs_are_limited_to_pushing_the_bundle_stream(self):
        for resources, names, verbs in [
            ("[repositories]", "[site-gateway]", "[get, update]"),
            ("[imagestreams/layers]", "[box1-ops-erp-simulator]", "[get, update]"),
            ("[imagestreams/layers]", "[site-gateway-bundle]", "[get, update, delete]"),
            ("[imagestreams/layers]", "[site-gateway-bundle]", "[create]"),
        ]:
            with self.subTest(resources=resources, names=names, verbs=verbs):
                self.rejects("may only get, list or watch", *self.extra(f"""
                    apiVersion: rbac.authorization.k8s.io/v1
                    kind: Role
                    metadata: {{name: site-gateway-write, namespace: box1-ci}}
                    rules:
                      - apiGroups: ['', image.openshift.io, pipelinesascode.tekton.dev]
                        resources: {resources}
                        resourceNames: {names}
                        verbs: {verbs}
                """))

    def test_rolebinding_must_reference_a_role_from_the_bundle(self):
        self.rejects("must reference a Role declared in ci/site-gateway", *self.extra("""
            apiVersion: rbac.authorization.k8s.io/v1
            kind: RoleBinding
            metadata: {name: site-gateway-admin, namespace: box1-ci}
            roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: admin}
            subjects: [{kind: ServiceAccount, name: site-gateway-release, namespace: box1-ci}]
        """))

    def test_rolebinding_subjects_are_bundle_accounts_or_ci_observe(self):
        for subject in ["{kind: ServiceAccount, name: pipeline, namespace: box1-ci}",
                        "{kind: ServiceAccount, name: site-gateway-release, namespace: default}",
                        "{kind: Group, name: 'system:authenticated', apiGroup: rbac.authorization.k8s.io}",
                        "{kind: User, name: mallory, apiGroup: rbac.authorization.k8s.io}"]:
            with self.subTest(subject=subject):
                self.rejects("may bind only", *self.extra(f"""
                    apiVersion: rbac.authorization.k8s.io/v1
                    kind: RoleBinding
                    metadata: {{name: site-gateway-extra, namespace: box1-ci}}
                    roleRef: {{apiGroup: rbac.authorization.k8s.io, kind: Role, name: site-gateway-release-observer}}
                    subjects: [{subject}]
                """))


@unittest.skipUnless(KUSTOMIZE, "kubectl or oc is required to render fixtures")
class ValidationTargets(unittest.TestCase):
    """The Task validates workloads/*/ and ci/*/; a ci/ name must not shadow a workload."""

    @classmethod
    def setUpClass(cls):
        cls.v = load_validator()

    def tree(self, workloads, ci):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for kind, names in [("workloads", workloads), ("ci", ci)]:
            for n in names:
                (root / kind / n).mkdir(parents=True)
                (root / kind / n / "kustomization.yaml").write_text("resources: []\n")
        return root

    def test_workload_and_ci_targets_are_listed(self):
        root = self.tree(["order-service", "site-west"], ["site-gateway"])
        workloads, ci = self.v["validation_targets"](root)
        self.assertEqual([t.parent.name for t in workloads], ["order-service", "site-west"])
        self.assertEqual([t.parent.name for t in ci], ["site-gateway"])

    def test_missing_ci_directory_is_allowed(self):
        workloads, ci = self.v["validation_targets"](self.tree(["order-service"], []))
        self.assertEqual(ci, [])

    def test_ci_name_must_not_shadow_a_workload(self):
        with self.assertRaisesRegex(AssertionError, "ci/order-service collides with workloads/order-service"):
            self.v["validation_targets"](self.tree(["order-service"], ["order-service"]))

    def test_no_workloads_is_still_an_error(self):
        with self.assertRaisesRegex(AssertionError, "No workload targets found"):
            self.v["validation_targets"](self.tree([], ["site-gateway"]))


@unittest.skipUnless(KUSTOMIZE, "kubectl or oc is required to render the Tasks")
class TaskManifestsRender(unittest.TestCase):
    """The tests read the scripts as text; this catches YAML that Argo could not apply."""

    def test_tasks_kustomization_renders_both_tasks(self):
        rendered = subprocess.check_output([KUSTOMIZE, "kustomize", str(ROOT)], text=True)
        for task in ["box1-gitops-validate", "box1-gitops-promote"]:
            self.assertIn("  name: " + task + "\n", rendered)
        self.assertIn("- default: \"\"\n    description: vm-instance only.", rendered)


def declared_profile(rendered):
    """The profile a rendered workload declares on its Namespace (`service` when unlabelled).

    Read independently of the validator so the regression cannot agree with itself.
    """
    labels = re.findall(r"(?m)^    box1\.org/workload-profile: (\S+)$", rendered)
    return labels[0] if labels else "service"


@unittest.skipUnless(KUSTOMIZE and os.environ.get("BOX1_WORKLOADS_DEV"), "set BOX1_WORKLOADS_DEV to a box1-workloads-dev checkout")
class ServiceProfileRegression(unittest.TestCase):
    """Every live workload validates under the profile it declares (box1-docs#139).

    Before #139 this asserted `service` for every workload, which failed once
    legacy-erp and vm-golden-check declared `virtual-machine`.
    """

    def test_existing_service_workloads_still_validate(self):
        v = load_validator()
        checkout = pathlib.Path(os.environ["BOX1_WORKLOADS_DEV"])
        targets = sorted((checkout / "workloads").glob("*/kustomization.yaml"))
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(workload=target.parent.name):
                rendered = subprocess.check_output([KUSTOMIZE, "kustomize", str(target.parent)], text=True)
                self.assertEqual(v["validate"](target.parent.name, rendered), declared_profile(rendered))
        for target in sorted((checkout / "ci").glob("*/kustomization.yaml")):
            with self.subTest(ci=target.parent.name):
                rendered = subprocess.check_output([KUSTOMIZE, "kustomize", str(target.parent)], text=True)
                v["check_ci"](target.parent.name, rendered)
        v["validation_targets"](checkout)


if __name__ == "__main__":
    unittest.main()
