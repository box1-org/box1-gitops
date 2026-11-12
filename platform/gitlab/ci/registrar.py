"""PaC Repository CR + project webhook for each box1-gl project with .tekton on its default branch."""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

URL, GROUP, TOKEN = os.environ["GITLAB_URL"], os.environ["GITLAB_GROUP"], os.environ["GITLAB_TOKEN"]
HOOK_URL, HOOK_SECRET = os.environ["PAC_WEBHOOK_URL"], os.environ["WEBHOOK_SECRET"]
NS = "box1-gl-ci"
SA = "/var/run/secrets/kubernetes.io/serviceaccount"


def http(url, method="GET", body=None, headers=None, ctx=None):
    req = urllib.request.Request(url, method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:500]


def gl(path, method="GET", body=None):
    return http(f"{URL}/api/v4{path}", method, body,
                {"PRIVATE-TOKEN": TOKEN, "Content-Type": "application/json"})


def kube(method, path, body=None):
    token = open(f"{SA}/token").read().strip()
    return http(f"https://kubernetes.default.svc{path}", method, body,
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                ssl.create_default_context(cafile=f"{SA}/ca.crt"))


code, existing = kube("GET", f"/apis/pipelinesascode.tekton.dev/v1alpha1/namespaces/{NS}/repositories")
if code != 200:
    raise SystemExit(f"list repositories: HTTP {code} {existing}")
known = {r["spec"]["url"].rstrip("/") for r in existing["items"]}

code, projects = gl(f"/groups/{urllib.parse.quote(GROUP, safe='')}/projects?per_page=100&include_subgroups=false")
if code != 200:
    raise SystemExit(f"list projects: HTTP {code} {projects}")
for p in projects:
    url = p["web_url"].rstrip("/")
    code, _ = gl(f"/projects/{p['id']}/repository/tree?path=.tekton&ref={p['default_branch'] or 'main'}")
    if code != 200 or not _:
        continue
    code, hooks = gl(f"/projects/{p['id']}/hooks")
    if code == 200 and not any(h["url"] == HOOK_URL for h in hooks):
        code, body = gl(f"/projects/{p['id']}/hooks", "POST", {
            "url": HOOK_URL, "token": HOOK_SECRET, "push_events": True, "merge_requests_events": True,
            "note_events": True, "enable_ssl_verification": False})
        print(f"{p['path']}: webhook -> HTTP {code}" + ("" if code == 201 else f" {body}"), flush=True)
    if url in known:
        continue
    cr = {"apiVersion": "pipelinesascode.tekton.dev/v1alpha1", "kind": "Repository",
          "metadata": {"name": p["path"], "namespace": NS,
                       "labels": {"app.kubernetes.io/managed-by": "gl-registrar"}},
          "spec": {"url": url, "concurrency_limit": 1,
                   "git_provider": {"type": "gitlab", "url": URL,
                                    "secret": {"name": "gitlab-pac", "key": "provider.token"},
                                    "webhook_secret": {"name": "gitlab-pac", "key": "webhook.secret"}},
                   "settings": {"pipelinerun_provenance": "default_branch"}}}
    code, body = kube("POST", f"/apis/pipelinesascode.tekton.dev/v1alpha1/namespaces/{NS}/repositories", cr)
    print(f"{p['path']}: Repository CR -> HTTP {code}" + ("" if code == 201 else f" {body}"), flush=True)
