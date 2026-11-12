"""Idempotent GitLab CE bootstrap for the Box1 GitLab proof (box1-docs#164 re-run).

Modes:
  admin-secret  create gitlab/gitlab-admin (root password + root API token) if missing
  bootstrap     instance settings, group, accounts, tokens, GitOps repo,
                branch protection, project webhook and the consumer Secrets

The root token is seeded into GitLab by the container itself (seed-token.sh).
Standard library only. Tokens are never printed.
"""

import base64
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

P = os.environ
GL = P.get("GITLAB_INTERNAL_URL", "http://gitlab.gitlab.svc:8929").rstrip("/")
HOST = P["GITLAB_HOST"]
GROUP = P["GITLAB_GROUP"]            # service repositories (RHDH creates them)
GITOPS_GROUP = P["GITOPS_GROUP"]     # GitOps target, only promote-bot may merge
CI_NS = P["CI_NAMESPACE"]
GITOPS_REPO = P["GITOPS_REPO"]
DEV = P.get("DEVSPACES_USER", "box1-dev")
SEED_DIR = "/opt/seed"
SA = "/var/run/secrets/kubernetes.io/serviceaccount"
KUBE = "https://kubernetes.default.svc"

GUEST, REPORTER, DEVELOPER, MAINTAINER = 10, 20, 30, 40
# GitLab CE protects branches by role, not by user. So the GitOps repository
# lives in its own group where promote-bot is the only Maintainer (merge
# right), while the service group gives pac-bot Maintainer (it creates the
# project webhooks for new service repositories).
# account -> (service group level, gitops group level, token scopes)
ACCOUNTS = {
    "rhdh-bot": (DEVELOPER, None, ["api"]),
    "pac-bot": (MAINTAINER, DEVELOPER, ["api"]),
    "promote-bot": (REPORTER, MAINTAINER, ["api"]),
    "argocd-bot": (REPORTER, REPORTER, ["read_repository"]),
    DEV: (MAINTAINER, DEVELOPER, ["api", "write_repository"]),
}


def log(msg):
    print(f"[bootstrap] {msg}", flush=True)


# ---------------------------------------------------------------- Kubernetes
def kube(method, path, body=None, content_type="application/json"):
    token = open(f"{SA}/token").read().strip()
    req = urllib.request.Request(KUBE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", content_type)
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get_secret(ns, name):
    code, body = kube("GET", f"/api/v1/namespaces/{ns}/secrets/{name}")
    if code == 404:
        return None
    if code != 200:
        raise RuntimeError(f"get secret {ns}/{name}: HTTP {code} {body.get('message')}")
    return {k: base64.b64decode(v).decode() for k, v in (body.get("data") or {}).items()}


def put_secret(ns, name, data, labels=None):
    meta = {"name": name, "namespace": ns,
            "labels": {"app.kubernetes.io/managed-by": "gitlab-bootstrap", **(labels or {})}}
    body = {"apiVersion": "v1", "kind": "Secret", "metadata": meta, "type": "Opaque", "stringData": data}
    code, resp = kube("POST", f"/api/v1/namespaces/{ns}/secrets", body)
    if code == 409:
        code, resp = kube("PATCH", f"/api/v1/namespaces/{ns}/secrets/{name}",
                          {"metadata": meta, "stringData": data}, "application/merge-patch+json")
    if code not in (200, 201):
        raise RuntimeError(f"write secret {ns}/{name}: HTTP {code} {resp.get('message')}")
    log(f"secret {ns}/{name} written")


# ---------------------------------------------------------------- GitLab
def gl(method, path, body=None, token=None):
    req = urllib.request.Request(f"{GL}/api/v4{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    req.add_header("PRIVATE-TOKEN", token or ROOT)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, raw.decode(errors="replace")[:300]


def must(res, what, ok=(200, 201, 204)):
    code, data = res
    if code not in ok:
        raise RuntimeError(f"{what}: HTTP {code} {data}")
    return data


def enc(path):
    return urllib.parse.quote(path, safe="")


def token_works(token):
    code, _ = gl("GET", "/personal_access_tokens/self", token=token)
    return code == 200


# ---------------------------------------------------------------- modes
def admin_secret():
    if get_secret("gitlab", "gitlab-admin"):
        log("gitlab/gitlab-admin exists")
        return
    put_secret("gitlab", "gitlab-admin", {
        "username": "root",
        "password": secrets.token_urlsafe(24) + "aA1!",
        "token": "glpat-" + secrets.token_urlsafe(30).replace("-", "x").replace("_", "y")[:32],
    })


def wait_root():
    for _ in range(120):
        try:
            if token_works(ROOT):
                return
        except Exception:
            pass
        time.sleep(10)
    raise RuntimeError("root token not accepted: is GitLab up and seed-token.sh done?")


def settings():
    must(gl("PUT", "/application/settings", {
        "signup_enabled": False,
        "default_project_visibility": "private",
        "default_group_visibility": "private",
        "restricted_visibility_levels": ["public"],
        "import_sources": [],
        "usage_ping_enabled": False,
        "allow_local_requests_from_web_hooks_and_services": False,
        "outbound_local_requests_allowlist_raw": "pipelines-as-code-controller.openshift-pipelines.svc",
        "auto_devops_enabled": False,
    }), "application settings")
    log("instance settings applied")


def ensure_group(name, creation_level):
    code, g = gl("GET", f"/groups/{enc(name)}")
    if code == 404:
        g = must(gl("POST", "/groups", {"name": name, "path": name, "visibility": "private",
                                        "project_creation_level": creation_level,
                                        "auto_devops_enabled": False}), f"create group {name}")
        log(f"group {name} created")
    else:
        must(gl("PUT", f"/groups/{g['id']}", {"project_creation_level": creation_level}), f"group {name}")
    return g


def ensure_user(name):
    users = must(gl("GET", f"/users?username={name}"), f"find {name}")
    if users:
        return users[0]
    u = must(gl("POST", "/users", {"username": name, "name": name, "email": f"{name}@gitlab.invalid",
                                   "password": secrets.token_urlsafe(24) + "aA1!",
                                   "skip_confirmation": True, "private_profile": True}), f"create {name}")
    log(f"user {name} created")
    return u


def ensure_member(kind, ident, user, level):
    code, m = gl("GET", f"/{kind}/{ident}/members/{user['id']}")
    if code == 404:
        must(gl("POST", f"/{kind}/{ident}/members", {"user_id": user["id"], "access_level": level}),
             f"add {user['username']}")
    elif m["access_level"] != level:
        must(gl("PUT", f"/{kind}/{ident}/members/{user['id']}", {"access_level": level}),
             f"update {user['username']}")


def mint_token(user, scopes):
    for t in must(gl("GET", f"/personal_access_tokens?user_id={user['id']}&state=active"), "list tokens"):
        if t["name"] == "box1-bootstrap":
            gl("DELETE", f"/personal_access_tokens/{t['id']}")
    expires = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 360 * 86400))
    return must(gl("POST", f"/users/{user['id']}/personal_access_tokens",
                   {"name": "box1-bootstrap", "scopes": scopes, "expires_at": expires}),
                f"token for {user['username']}")["token"]


def ensure_gitops_repo(group, webhook_secret):
    path = f"{GITOPS_GROUP}/{GITOPS_REPO}"
    code, proj = gl("GET", f"/projects/{enc(path)}")
    if code == 404:
        proj = must(gl("POST", "/projects", {
            "name": GITOPS_REPO, "path": GITOPS_REPO, "namespace_id": group["id"],
            "visibility": "private", "initialize_with_readme": True, "default_branch": "main",
            "description": "GitLab proof GitOps target",
        }), "create gitops repo")
        log(f"project {path} created")
    pid = proj["id"]
    # Merge only with a successful pipeline (PaC's commit statuses), squash allowed.
    must(gl("PUT", f"/projects/{pid}", {
        "only_allow_merge_if_pipeline_succeeds": True,
        "allow_merge_on_skipped_pipeline": False,
        "only_allow_merge_if_all_discussions_are_resolved": False,
        "squash_option": "default_on", "remove_source_branch_after_merge": True,
        "merge_method": "merge", "auto_devops_enabled": False,
    }), "project merge settings")
    seed_and_protect(pid)
    ensure_hook(pid, webhook_secret)
    return pid


def seed_and_protect(pid):
    # GitLab CE protects by role only. main: nobody pushes, Maintainers merge;
    # in the GitOps group only promote-bot is a Maintainer. Seeding (root)
    # needs main briefly unprotected, and only happens when a file is missing.
    actions = []
    if os.path.isdir(SEED_DIR):
        for key in sorted(os.listdir(SEED_DIR)):
            if key.startswith(".."):
                continue
            path = key.replace("__", "/")
            code, _ = gl("GET", f"/projects/{pid}/repository/files/{enc(path)}?ref=main")
            if code == 404:
                actions.append({"action": "create", "file_path": path,
                                "content": open(os.path.join(SEED_DIR, key)).read()})
    if actions:
        gl("DELETE", f"/projects/{pid}/protected_branches/main")
        must(gl("POST", f"/projects/{pid}/repository/commits",
                {"branch": "main", "commit_message": "Seed from gitlab-bootstrap", "actions": actions}),
             "seed files")
        log(f"seeded {len(actions)} file(s)")
    code, pb = gl("GET", f"/projects/{pid}/protected_branches/main")
    want = {"push": 0, "merge": MAINTAINER}
    if code == 200:
        have = {"push": pb["push_access_levels"][0]["access_level"] if pb["push_access_levels"] else None,
                "merge": pb["merge_access_levels"][0]["access_level"] if pb["merge_access_levels"] else None}
        if have == want and not pb.get("allow_force_push"):
            log("branch protection on main already correct")
            return
        gl("DELETE", f"/projects/{pid}/protected_branches/main")
    must(gl("POST", f"/projects/{pid}/protected_branches",
            {"name": "main", "push_access_level": 0, "merge_access_level": MAINTAINER,
             "allow_force_push": False}), "protect main")
    log("branch protection on main: push=No one, merge=Maintainers")


def ensure_hook(pid, secret):
    url = P["PAC_WEBHOOK_URL"]
    body = {"url": url, "token": secret, "push_events": True, "merge_requests_events": True,
            "note_events": True, "tag_push_events": False, "enable_ssl_verification": False}
    hooks = must(gl("GET", f"/projects/{pid}/hooks"), "list hooks")
    match = [h for h in hooks if h["url"] == url]
    if match:
        must(gl("PUT", f"/projects/{pid}/hooks/{match[0]['id']}", body), "update hook")
    else:
        must(gl("POST", f"/projects/{pid}/hooks", body), "create hook")
    log(f"project webhook -> {url}")


def bootstrap():
    wait_root()
    settings()
    group = ensure_group(GROUP, "developer")
    gitops = ensure_group(GITOPS_GROUP, "noone")
    ci, rhdh, argo = CI_NS, P["RHDH_NAMESPACE"], P["ARGOCD_NAMESPACE"]
    where = {
        "rhdh-bot": (rhdh, "developer-hub-gitlab-secrets", "GITLAB_TOKEN",
                     lambda u, t: ({"GITLAB_TOKEN": t}, {})),
        "pac-bot": (ci, "gitlab-pac", "provider.token", None),
        "promote-bot": (ci, "gitlab-promote", "token", lambda u, t: ({"username": u, "token": t}, {})),
        "argocd-bot": (argo, "gitlab-repo-creds", "password",
                       lambda u, t: ({"type": "git", "url": f"https://{HOST}/", "username": u,
                                      "password": t}, {"argocd.argoproj.io/secret-type": "repo-creds"})),
        DEV: ("gitlab", "gitlab-dev-token", "token", lambda u, t: ({"username": u, "token": t}, {})),
    }
    users = {}
    webhook = None
    for name, (level, gitops_level, scopes) in ACCOUNTS.items():
        user = users[name] = ensure_user(name)
        ensure_member("groups", group["id"], user, level)
        if gitops_level:
            ensure_member("groups", gitops["id"], user, gitops_level)
        ns, sname, key, build = where[name]
        current = get_secret(ns, sname) or {}
        token = current.get(key)
        if token and token_works(token):
            log(f"{name}: token in {ns}/{sname} still valid")
        else:
            token = mint_token(user, scopes)
            log(f"{name}: new token")
            if build:
                data, labels = build(name, token)
                put_secret(ns, sname, data, labels)
        if name == "pac-bot":
            webhook = current.get("webhook.secret") or secrets.token_urlsafe(32)
            if current.get("provider.token") != token or current.get("webhook.secret") != webhook:
                put_secret(ns, sname, {"provider.token": token, "webhook.secret": webhook})
    ensure_gitops_repo(gitops, webhook)
    log("done")


ROOT = None
if __name__ == "__main__":
    if sys.argv[1] == "bootstrap":
        ROOT = get_secret("gitlab", "gitlab-admin")["token"]
    {"admin-secret": admin_secret, "bootstrap": bootstrap}[sys.argv[1]]()
