"""Policy check for a workloads-proof merge request (box1-docs#164, GitLab re-run).

Reads the PR's changed files (CHANGED_FILES, newline separated) and the JSON
that `oc create --dry-run=client -o json` produced for each one under
/workspace/json/<path>.json. Fails unless:

  * every changed file is apps/<name>/{deployment,service,route}.yaml
  * every object is a Deployment, Service or Route, without a namespace
    other than the target namespace
  * every container image is the CI registry path pinned by digest
"""

import json
import os
import re
import sys

ALLOWED = re.compile(r"apps/([a-z][a-z0-9-]{1,40})/(deployment|service|route)\.yaml")
KINDS = {"Deployment", "Service", "Route"}
NS = os.environ.get("DEV_NAMESPACE", "box1-gl-dev")
IMAGE = re.compile(re.escape(os.environ["IMAGE_PREFIX"]) + r"[a-z][a-z0-9-]{1,40}@sha256:[0-9a-f]{64}")

errors = []
changed = [f for f in os.environ.get("CHANGED_FILES", "").split() if f]
if not changed:
    errors.append("no changed files reported")
for path in changed:
    m = ALLOWED.fullmatch(path)
    if not m:
        errors.append(f"{path}: only apps/<name>/(deployment|service|route).yaml may change")
        continue
    jpath = f"/workspace/json/{path}.json"
    if not os.path.exists(jpath):
        print(f"{path}: deleted")
        continue
    doc = json.load(open(jpath))
    items = doc.get("items", [doc]) if doc.get("kind") == "List" else [doc]
    for obj in items:
        kind, meta = obj.get("kind"), obj.get("metadata", {})
        if kind not in KINDS:
            errors.append(f"{path}: kind {kind} is not allowed")
        if meta.get("namespace") not in (None, NS):
            errors.append(f"{path}: namespace {meta.get('namespace')} is not allowed")
        if meta.get("name") != m.group(1):
            errors.append(f"{path}: object name {meta.get('name')} must be {m.group(1)}")
        if kind == "Deployment":
            spec = obj["spec"]["template"]["spec"]
            for c in spec.get("containers", []) + spec.get("initContainers", []):
                if not IMAGE.fullmatch(c.get("image", "")):
                    errors.append(f"{path}: image {c.get('image')} is not a digest-pinned CI image")
    print(f"{path}: checked")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("workloads-proof policy: OK")
