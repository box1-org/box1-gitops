"""Safe GitOps promotion on GitLab CE (box1-docs#164, GitLab re-run).

Same guards as platform/pipelines/tasks/gitops-promote.yaml, ported to the
GitLab REST API:

  1. the source revision must still be the head of the service's main
  2. one commit on a promote/ branch changes only the expected files
  3. the MR author, head SHA and exact file list are re-checked
  4. the required status contexts are green on that exact head SHA
  5. the squash merge is pinned with sha= (stale head => 409)
  6. Argo CD syncs the merge commit; the pod runs the digest and the
     service reports the source revision
"""

import base64
import fnmatch
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

E = os.environ
GL = E["GITLAB_URL"].rstrip("/")
SRC_GROUP = E["SOURCE_GROUP"]
GITOPS = E["GITOPS_PROJECT"]          # group/path
APP = E["APP_NAME"]
REV = E["SOURCE_REVISION"]
DIGEST = E["IMAGE_DIGEST"]
IMAGE_REPO = E["IMAGE_REPOSITORY"]
PIPELINE_RUN = E.get("PIPELINE_RUN", "")
CONTEXTS = [c.strip() for c in E.get("REQUIRED_CONTEXTS", "").split(",") if c.strip()]
DEV_NS = E["DEV_NAMESPACE"]
ARGO_APP = E["ARGO_APPLICATION"]
TOKEN = open("/etc/gitlab-token/token").read().strip()
BOT = open("/etc/gitlab-token/username").read().strip()
RESULTS = "/tekton/results"
SA = "/var/run/secrets/kubernetes.io/serviceaccount"

if not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", APP):
    sys.exit(f"invalid application name {APP!r}")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", DIGEST):
    sys.exit(f"invalid image digest {DIGEST!r}")
if not re.fullmatch(r"[0-9a-f]{40}", REV):
    sys.exit(f"invalid source revision {REV!r}")
if not CONTEXTS:
    sys.exit("REQUIRED_CONTEXTS is empty: refusing to merge without required checks")

q = lambda s: urllib.parse.quote(s, safe="")
SRC = q(f"{SRC_GROUP}/{APP}")
GP = q(GITOPS)


def log(msg):
    print(f"[promote] {msg}", flush=True)


def result(name, value):
    with open(f"{RESULTS}/{name}", "w") as f:
        f.write(value)


def http(url, method="GET", body=None, headers=None, ctx=None):
    req = urllib.request.Request(url, method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, raw.decode(errors="replace")[:300]


def gl(method, path, body=None):
    return http(f"{GL}/api/v4{path}", method, body, {"PRIVATE-TOKEN": TOKEN, "Content-Type": "application/json"})


def must(res, what):
    code, data = res
    if code not in (200, 201, 202, 204):
        sys.exit(f"{what}: HTTP {code} {data}")
    return data


def kube(method, path, body=None, ctype="application/json"):
    token = open(f"{SA}/token").read().strip()
    return http(f"https://kubernetes.default.svc{path}", method, body,
                {"Authorization": f"Bearer {token}", "Content-Type": ctype},
                ssl.create_default_context(cafile=f"{SA}/ca.crt"))


def source_head():
    return must(gl("GET", f"/projects/{SRC}/repository/branches/main"), "source main")["commit"]["id"]


IMAGE = f"{IMAGE_REPO}@{DIGEST}"


def new_manifests():
    deployment = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {APP}
  labels:
    app.kubernetes.io/name: {APP}
    backstage.io/kubernetes-id: {APP}
  annotations:
    box1.org/source-repository: {SRC_GROUP}/{APP}
    box1.org/source-revision: {REV}  # promote:source-revision
    box1.org/pipeline-run: {PIPELINE_RUN}  # promote:pipeline-run
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {APP}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {APP}
        backstage.io/kubernetes-id: {APP}
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: {APP}
          image: {IMAGE}  # promote:image
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet: {{path: /healthz, port: http}}
          resources:
            requests: {{cpu: 10m, memory: 32Mi}}
            limits: {{cpu: 200m, memory: 128Mi}}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
"""
    service = f"""apiVersion: v1
kind: Service
metadata:
  name: {APP}
  labels:
    backstage.io/kubernetes-id: {APP}
spec:
  selector:
    app.kubernetes.io/name: {APP}
  ports:
    - name: http
      port: 8080
      targetPort: http
"""
    route = f"""apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: {APP}
  labels:
    backstage.io/kubernetes-id: {APP}
spec:
  to:
    kind: Service
    name: {APP}
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
"""
    return {f"apps/{APP}/deployment.yaml": deployment,
            f"apps/{APP}/service.yaml": service,
            f"apps/{APP}/route.yaml": route}


def updated_deployment(text):
    out, hits = [], set()
    for line in text.splitlines(keepends=True):
        for marker, value in (("promote:image", f"image: {IMAGE}"),
                              ("promote:source-revision", f"box1.org/source-revision: {REV}"),
                              ("promote:pipeline-run", f"box1.org/pipeline-run: {PIPELINE_RUN}")):
            if line.rstrip().endswith(f"# {marker}"):
                indent = line[:len(line) - len(line.lstrip())]
                line = f"{indent}{value}  # {marker}\n"
                hits.add(marker)
        out.append(line)
    if len(hits) != 3:
        sys.exit("deployment.yaml is missing promote markers")
    return "".join(out)


def main():
    result("promoted", "false")
    result("merge-commit", "")
    result("pr-url", "")

    if source_head() != REV:
        log(f"{REV[:12]} is no longer the head of {SRC_GROUP}/{APP} main: not promoting a superseded build")
        return

    path = f"apps/{APP}/deployment.yaml"
    code, current = gl("GET", f"/projects/{GP}/repository/files/{q(path)}?ref=main")
    if code == 404:
        files = new_manifests()
        actions = [{"action": "create", "file_path": p, "content": c} for p, c in files.items()]
        log("first promotion: adding deployment, service and route")
    elif code == 200:
        text = base64.b64decode(current["content"]).decode()
        new = updated_deployment(text)
        if new == text:
            log("image and provenance already promoted: nothing to do")
            result("promoted", "true")
            return
        files = {path: new}
        actions = [{"action": "update", "file_path": path, "content": new,
                    "last_commit_id": current["last_commit_id"]}]
    else:
        sys.exit(f"read {path}: HTTP {code}")

    branch = f"promote/{APP}-{REV[:12]}"
    commit = must(gl("POST", f"/projects/{GP}/repository/commits", {
        "branch": branch, "start_branch": "main", "actions": actions,
        "commit_message": f"Promote {APP} to {DIGEST[:19]}\n\nSource: {SRC_GROUP}/{APP}@{REV}\nPipelineRun: {PIPELINE_RUN}",
    }), "create promotion commit")
    head = commit["id"]
    log(f"branch {branch} at {head[:12]}")

    mr = must(gl("POST", f"/projects/{GP}/merge_requests", {
        "source_branch": branch, "target_branch": "main",
        "title": f"Promote {APP} {REV[:12]}",
        "description": f"Image `{IMAGE}`\n\nSource `{SRC_GROUP}/{APP}@{REV}`, PipelineRun `{PIPELINE_RUN}`.\n\nOpened by gitlab-gitops-promote.",
        "remove_source_branch": True, "squash": True,
    }), "open MR")
    iid = mr["iid"]
    result("pr-url", mr["web_url"])
    log(f"opened {mr['web_url']}")

    # Guards on the MR as GitLab sees it. diff_refs/sha can lag a moment.
    for _ in range(12):
        mr = must(gl("GET", f"/projects/{GP}/merge_requests/{iid}"), "read MR")
        if mr.get("sha") == head:
            break
        time.sleep(5)
    if mr["author"]["username"] != BOT:
        sys.exit(f"MR author {mr['author']['username']} is not {BOT}")
    if mr["sha"] != head:
        sys.exit("MR head moved after it was opened")
    # GitLab builds the MR diff asynchronously: wait until it exists for this head.
    changed = set()
    for _ in range(24):
        mr = must(gl("GET", f"/projects/{GP}/merge_requests/{iid}"), "read MR")
        if (mr.get("diff_refs") or {}).get("head_sha") == head:
            diffs = must(gl("GET", f"/projects/{GP}/merge_requests/{iid}/diffs?per_page=100"), "MR diffs")
            changed = {d["new_path"] for d in diffs} | {d["old_path"] for d in diffs}
            if changed:
                break
        time.sleep(5)
    if changed != set(files):
        sys.exit(f"MR changes unexpected files: {sorted(changed ^ set(files))}")

    deadline = time.time() + 20 * 60
    while True:
        statuses = must(gl("GET", f"/projects/{GP}/repository/commits/{head}/statuses?per_page=100&all=true"), "statuses")
        latest = {}
        for s in sorted(statuses, key=lambda s: s["id"]):
            latest[s["name"]] = s["status"]
        states = {pat: [st for n, st in latest.items() if fnmatch.fnmatch(n, pat)] for pat in CONTEXTS}
        if any(set(v) & {"failed", "canceled"} for v in states.values()):
            sys.exit(f"required check failed on {head[:12]}: {latest}")
        if all(v and all(s == "success" for s in v) for v in states.values()):
            log(f"required checks green on {head[:12]}: {latest}")
            break
        if time.time() > deadline:
            sys.exit(f"timed out waiting for required checks on {head[:12]}: {latest}")
        time.sleep(10)

    # GitLab computes mergeability asynchronously; wait for it, then re-check.
    for _ in range(30):
        mr = must(gl("GET", f"/projects/{GP}/merge_requests/{iid}?include_rebase_in_progress=true"), "re-read MR")
        if mr.get("detailed_merge_status") not in ("checking", "unchecked", "preparing", "ci_still_running", "ci_must_pass"):
            break
        time.sleep(5)
    if mr["sha"] != head or mr["state"] != "opened":
        sys.exit("MR head or state changed while waiting for checks")
    if source_head() != REV:
        log("source main moved while waiting: leaving the MR open, not merging a superseded build")
        return

    code, merged = gl("PUT", f"/projects/{GP}/merge_requests/{iid}/merge", {
        "sha": head, "squash": True, "should_remove_source_branch": True,
        "squash_commit_message": f"Promote {APP} {REV[:12]} (!{iid})",
    })
    if code != 200:
        sys.exit(f"merge refused: HTTP {code} {merged} (detailed_merge_status={mr.get('detailed_merge_status')})")
    merge_sha = merged.get("merge_commit_sha") or merged.get("squash_commit_sha") or ""
    if merged.get("state") != "merged" or not merge_sha:
        sys.exit(f"MR is not reported as merged: {merged.get('state')}")
    target_head = must(gl("GET", f"/projects/{GP}/repository/branches/main"), "gitops main")["commit"]["id"]
    if target_head != merge_sha:
        log(f"note: main head {target_head[:12]} differs from merge_commit_sha {merge_sha[:12]}; using main head")
        merge_sha = target_head
    result("merge-commit", merge_sha)
    log(f"squash-merged at {merge_sha[:12]}")

    gitops = "/apis/argoproj.io/v1alpha1/namespaces/openshift-gitops/applications/" + ARGO_APP
    code, _ = kube("PATCH", gitops, {"metadata": {"annotations": {"argocd.argoproj.io/refresh": "hard"}}},
                   "application/merge-patch+json")
    if code != 200:
        sys.exit(f"refresh {ARGO_APP}: HTTP {code}")
    deadline = time.time() + 10 * 60
    requested = False
    while time.time() < deadline:
        code, app = kube("GET", gitops)
        if code != 200:
            sys.exit(f"read {ARGO_APP}: HTTP {code}")
        st = app.get("status", {})
        op = st.get("operationState", {})
        running = app.get("operation") or op.get("phase") in ("Running", "Terminating")
        if not requested and not running:
            code, _ = kube("PATCH", gitops, {"operation": {"initiatedBy": {"username": "gitlab-gitops-promote"},
                                                           "sync": {"revision": merge_sha}}},
                           "application/merge-patch+json")
            if code != 200:
                sys.exit(f"sync {ARGO_APP}: HTTP {code}")
            requested = True
            log(f"Argo CD sync requested at {merge_sha[:12]}")
        elif (requested and not running and op.get("syncResult", {}).get("revision") == merge_sha
              and op.get("phase") == "Succeeded" and st.get("health", {}).get("status") == "Healthy"):
            log(f"{ARGO_APP} synced and Healthy at {merge_sha[:12]}")
            break
        elif requested and op.get("phase") in ("Failed", "Error") and op.get("syncResult", {}).get("revision") == merge_sha:
            sys.exit(f"Argo CD sync failed: {op.get('message')}")
        time.sleep(10)
    else:
        sys.exit("timed out waiting for Argo CD")

    deadline = time.time() + 5 * 60
    while time.time() < deadline:
        code, pods = kube("GET", f"/api/v1/namespaces/{DEV_NS}/pods?labelSelector=app.kubernetes.io/name%3D{APP}")
        items = [p for p in pods.get("items", []) if p["metadata"].get("deletionTimestamp") is None]
        ready = [p for p in items if any(c.get("ready") and c.get("imageID", "").endswith(DIGEST)
                                         for c in p.get("status", {}).get("containerStatuses", []))]
        stale = [p for p in items if not any(c.get("imageID", "").endswith(DIGEST)
                                             for c in p.get("status", {}).get("containerStatuses", []))]
        if ready and not stale:
            log(f"pod {ready[0]['metadata']['name']} Ready with {DIGEST[:19]}")
            break
        time.sleep(5)
    else:
        sys.exit("no Ready pod running the promoted digest")

    code, route = kube("GET", f"/apis/route.openshift.io/v1/namespaces/{DEV_NS}/routes/{APP}")
    host = route["spec"]["host"]
    for _ in range(30):
        code, body = http(f"https://{host}/")
        if code == 200 and isinstance(body, dict) and body.get("revision") == REV:
            log(f"https://{host}/ reports revision {REV[:12]}: {body}")
            result("promoted", "true")
            return
        time.sleep(5)
    sys.exit(f"https://{host}/ did not report revision {REV}: HTTP {code} {body}")


main()
