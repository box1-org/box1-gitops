#!/usr/bin/env python3
"""Render the RHDP entry chart the way Argo CD would and check the results.

For every scenario this script:
  1. runs `helm template` on rhdp/ with the scenario's values;
  2. checks the child Applications (unique names and paths, retry, sync options);
  3. builds every child source in a scratch copy of the repository: kustomize
     sources get their Application's kustomize.patches/images appended to the
     kustomization (what Argo CD's `kustomize edit` does), Helm sources get
     their inline values;
  4. scans the built manifests for homelab-only values.

Needs: helm, kubectl (kustomize), python3 with PyYAML.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: python3 -m pip install pyyaml (or set PYTHON to an interpreter that has it)")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHART = os.path.join(ROOT, "rhdp")
DOMAIN = "apps.cluster-test.example.com"
SENTINEL = "sk-test-SENTINEL-litemaas"

BASE = {
    "deployer": {"domain": DOMAIN, "apiUrl": "https://api.cluster-test.example.com:6443"},
    "gitops": {"repoURL": "https://github.com/box1-rhdp/box1-gitops.git", "revision": "rhdp", "path": "rhdp"},
}

# Homelab-only values that must not survive in any built manifest.
FORBIDDEN = [
    r"apps\.ocp\.box1\.org",
    r"api\.ocp\.box1\.org",
    r"lvms-vg1",
    r"redhat-operators-v4\d+",
    r"/auth/realms",
    r"ocp-v5\.0-art-dev",
    r"installPlanApproval\"?: \"?Manual",
    r"mike-sandbox",
    r"vllm-test-2",
    r"api\.openai\.com",
    r"rhtpa-redhat-current",
    r"letsencrypt-production",
    r"box1-rhtpa-89c9420e",
    r"%!",  # malformed Helm printf output
]


def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{p.stderr.strip()}")
    return p.stdout


def helm_template(name, chart, values, tmp, namespace=None):
    vf = os.path.join(tmp, f"{name}-values.yaml")
    with open(vf, "w") as f:
        yaml.safe_dump(values, f)
    cmd = ["helm", "template", name, chart, "-f", vf]
    if namespace:
        cmd += ["--namespace", namespace]
    return run(cmd)


def load_all(text):
    return [d for d in yaml.safe_load_all(text) if d]


def apply_argo_kustomize(kdir, kust):
    """Append Application kustomize patches/images like `kustomize edit` does."""
    kfile = None
    for n in ("kustomization.yaml", "kustomization.yml", "Kustomization"):
        if os.path.exists(os.path.join(kdir, n)):
            kfile = os.path.join(kdir, n)
            break
    if kfile is None:
        raise RuntimeError(f"no kustomization in {kdir}")
    with open(kfile) as f:
        k = yaml.safe_load(f) or {}
    for p in kust.get("patches", []) or []:
        k.setdefault("patches", []).append(p)
    for img in kust.get("images", []) or []:
        old, new = img.split("=", 1)
        entry = {"name": old}
        if "@" in new:
            entry["newName"], entry["digest"] = new.split("@", 1)
        else:
            slash = new.rfind("/")
            colon = new.rfind(":")
            if colon > slash:
                entry["newName"], entry["newTag"] = new[:colon], new[colon + 1:]
            else:
                entry["newName"] = new
        k.setdefault("images", []).append(entry)
    with open(kfile, "w") as f:
        yaml.safe_dump(k, f, sort_keys=False)


class Scenario:
    def __init__(self, name, values, expect=None, absent=None, allow=None, check=None):
        self.name = name
        self.values = deep_merge(BASE, values)
        self.expect = set(expect or [])      # Application names that must render
        self.absent = set(absent or [])      # Application names that must not render
        self.allow = allow or {}             # app name -> extra allowed regexes
        self.check = check                   # optional callable(apps, built) -> list of errors


def build(scenario, workdir):
    errors = []
    root_out = helm_template("box1-rhdp", CHART, scenario.values, workdir)
    docs = load_all(root_out)
    apps = [d for d in docs if d.get("kind") == "Application"]
    names = [a["metadata"]["name"] for a in apps]
    paths = [(a["spec"]["source"]["repoURL"], a["spec"]["source"]["path"]) for a in apps]
    for n in set(names):
        if names.count(n) > 1:
            errors.append(f"duplicate Application name {n}")
    for p in set(paths):
        if paths.count(p) > 1:
            errors.append(f"two Applications share source {p}")
    for a in apps:
        sp = a["spec"]["syncPolicy"]
        if "retry" not in sp:
            errors.append(f"{a['metadata']['name']}: no retry")
        for opt in ("SkipDryRunOnMissingResource=true", "CreateNamespace=true"):
            if opt not in sp.get("syncOptions", []):
                errors.append(f"{a['metadata']['name']}: missing {opt}")
    missing = scenario.expect - set(names)
    extra = scenario.absent & set(names)
    if missing:
        errors.append(f"missing Applications: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected Applications: {sorted(extra)}")

    # Root resources other than Applications (system namespace, plan, secrets).
    built = {"<root>": yaml.safe_dump_all([d for d in docs if d.get("kind") != "Application"])}

    repo = os.path.join(workdir, "repo")
    if not os.path.exists(repo):
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git"))
    for a in apps:
        name = a["metadata"]["name"]
        src = a["spec"]["source"]
        if src["repoURL"] != scenario.values["gitops"]["repoURL"]:
            built[name] = ""  # external repository (e.g. workloads-dev fork)
            continue
        path = os.path.join(repo, src["path"])
        kfile = os.path.join(path, "kustomization.yaml")
        saved = open(kfile).read() if os.path.exists(kfile) else None
        try:
            if "helm" in src:
                vals = yaml.safe_load(src["helm"].get("values") or "{}") or {}
                built[name] = helm_template(name, path, vals, workdir, a["spec"]["destination"].get("namespace"))
            else:
                if "kustomize" in src:
                    apply_argo_kustomize(path, src["kustomize"])
                built[name] = run(["kubectl", "kustomize", path])
        except RuntimeError as e:
            errors.append(f"{name}: build failed: {e}")
            built[name] = ""
        finally:
            if saved is not None:
                with open(kfile, "w") as f:
                    f.write(saved)

    org = scenario.values.get("git", {}).get("org", "box1-org")
    odf = scenario.values.get("storage", {}).get("objectStore", "none") == "odf"
    for name, text in built.items():
        patterns = list(FORBIDDEN)
        if org != "box1-org":
            patterns.append(r"github\.com/box1-org/")
        if not odf:
            patterns.append(r"noobaa")
        allowed = [re.compile(x) for x in scenario.allow.get(name, [])]
        for pat in patterns:
            for m in re.finditer(pat, text):
                line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
                if any(al.search(line) for al in allowed):
                    continue
                errors.append(f"{name}: forbidden /{pat}/ in: {line.strip()[:160]}")
                break
        if SENTINEL in text and name != "<root>":
            errors.append(f"{name}: LiteMaaS key leaked into a child source")
    if SENTINEL in root_out:
        # Only the box1-rhdp-litemaas Secret may carry it.
        for d in docs:
            if SENTINEL in json.dumps(d) and not (d.get("kind") == "Secret" and d["metadata"]["name"] == "box1-rhdp-litemaas"):
                errors.append(f"LiteMaaS key appears in {d.get('kind')}/{d['metadata']['name']}")
    if scenario.check:
        errors += scenario.check(apps, built)
    return names, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", "--only", help="run scenarios whose name contains this text")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(__file__))
    from scenarios import SCENARIOS  # noqa: E402

    failed = 0
    for sc in SCENARIOS(Scenario, SENTINEL):
        if args.only and args.only not in sc.name:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                names, errors = build(sc, tmp)
            except RuntimeError as e:
                names, errors = [], [str(e)]
        status = "ok" if not errors else "FAIL"
        print(f"[{status}] {sc.name}: {len(names)} Applications")
        if args.verbose:
            print("      " + ", ".join(sorted(names)))
        for e in errors:
            print(f"      - {e}")
        failed += bool(errors)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
