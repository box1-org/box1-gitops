"""Create a PaC Repository CR for each box1-fj repository with .tekton on main."""
import json
import os
import ssl
import urllib.error
import urllib.request

URL, ORG, TOKEN = os.environ["FORGEJO_URL"], os.environ["FORGEJO_ORG"], os.environ["FORGEJO_TOKEN"]
NS = "box1-fj-ci"
SA = "/var/run/secrets/kubernetes.io/serviceaccount"


def http(url, method="GET", body=None, headers=None, ctx=None):
    req = urllib.request.Request(url, method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def fj(path):
    return http(f"{URL}/api/v1{path}", headers={"Authorization": f"token {TOKEN}"})


def kube(method, path, body=None):
    token = open(f"{SA}/token").read().strip()
    return http(f"https://kubernetes.default.svc{path}", method, body,
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                ssl.create_default_context(cafile=f"{SA}/ca.crt"))


code, existing = kube("GET", f"/apis/pipelinesascode.tekton.dev/v1alpha1/namespaces/{NS}/repositories")
if code != 200:
    raise SystemExit(f"list repositories: HTTP {code}")
known = {r["spec"]["url"].rstrip("/") for r in existing["items"]}

page = 1
while True:
    code, repos = fj(f"/orgs/{ORG}/repos?limit=50&page={page}")
    if code != 200:
        raise SystemExit(f"list org repos: HTTP {code}")
    if not repos:
        break
    for repo in repos:
        url = repo["html_url"].rstrip("/")
        if url in known:
            continue
        code, _ = fj(f"/repos/{ORG}/{repo['name']}/contents/.tekton?ref={repo['default_branch']}")
        if code != 200:
            continue
        cr = {
            "apiVersion": "pipelinesascode.tekton.dev/v1alpha1", "kind": "Repository",
            "metadata": {"name": repo["name"], "namespace": NS,
                         "labels": {"app.kubernetes.io/managed-by": "fj-registrar"}},
            "spec": {
                "url": url, "concurrency_limit": 1,
                "git_provider": {"type": "gitea", "url": URL, "user": "pac-bot",
                                 "secret": {"name": "forgejo-pac", "key": "provider.token"},
                                 "webhook_secret": {"name": "forgejo-pac", "key": "webhook.secret"}},
                "settings": {"pipelinerun_provenance": "default_branch"},
            },
        }
        code, _ = kube("POST", f"/apis/pipelinesascode.tekton.dev/v1alpha1/namespaces/{NS}/repositories", cr)
        print(f"{repo['name']}: Repository CR create -> HTTP {code}", flush=True)
    page += 1
