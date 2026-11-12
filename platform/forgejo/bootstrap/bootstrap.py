"""Idempotent Forgejo bootstrap for the Box1 Forgejo proof (box1-docs#164).

Modes:
  admin-secret  create forgejo/forgejo-admin (random password) if missing
  bootstrap     org, accounts, tokens, GitOps repo, branch protection,
                org webhook and the consumer Secrets

Only the standard library is used. Tokens are never printed. A consumer
Secret is rewritten only when it is missing or its token no longer works.
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
FORGEJO = P.get("FORGEJO_INTERNAL_URL", "http://forgejo.forgejo.svc:3000").rstrip("/")
HOST = P["FORGEJO_HOST"]
ORG = P["FORGEJO_ORG"]
CI_NS = P["CI_NAMESPACE"]
GITOPS_REPO = P["GITOPS_REPO"]
SEED_DIR = "/opt/seed"

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
KUBE = "https://kubernetes.default.svc"

# Account -> (team, token scopes). Scopes follow Forgejo's token scope names.
ACCOUNTS = {
    "rhdh-bot": ("writers", ["write:repository", "write:organization", "read:user"]),
    # Repo admin: PaC asks Forgejo for the PR author's permission on the repo,
    # which Forgejo allows only to repo admins. Scoped token, no admin:* scope.
    "pac-bot": ("ci-admins", ["write:repository", "write:issue", "read:user", "read:organization"]),
    "promote-bot": ("writers", ["write:repository", "write:issue", "read:user"]),
    "argocd-bot": ("readers", ["read:repository"]),
    P.get("DEVSPACES_USER", "box1-dev"): ("writers", ["write:repository", "write:issue", "read:user"]),
}
TEAM_UNITS = ["repo.code", "repo.issues", "repo.pulls", "repo.releases"]


def log(msg):
    print(f"[bootstrap] {msg}", flush=True)


# ---------------------------------------------------------------- Kubernetes
def _kube_ctx():
    return ssl.create_default_context(cafile=f"{SA}/ca.crt")


def kube(method, path, body=None, content_type="application/json"):
    token = open(f"{SA}/token").read().strip()
    req = urllib.request.Request(KUBE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, context=_kube_ctx(), timeout=30) as r:
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


def put_secret(ns, name, data, labels=None, annotations=None):
    meta = {"name": name, "namespace": ns,
            "labels": {"app.kubernetes.io/managed-by": "forgejo-bootstrap", **(labels or {})},
            "annotations": annotations or {}}
    body = {"apiVersion": "v1", "kind": "Secret", "metadata": meta, "type": "Opaque",
            "stringData": data}
    code, resp = kube("POST", f"/api/v1/namespaces/{ns}/secrets", body)
    if code == 409:
        code, resp = kube("PATCH", f"/api/v1/namespaces/{ns}/secrets/{name}",
                          {"metadata": meta, "stringData": data},
                          "application/merge-patch+json")
    if code not in (200, 201):
        raise RuntimeError(f"write secret {ns}/{name}: HTTP {code} {resp.get('message')}")
    log(f"secret {ns}/{name} written")


# ---------------------------------------------------------------- Forgejo
def fj(method, path, body=None, auth=None, token=None, ok=(200, 201, 204)):
    req = urllib.request.Request(f"{FORGEJO}/api/v1{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"token {token}")
    elif auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = raw.decode(errors="replace")
        if e.code in ok:
            return e.code, data
        return e.code, data


def must(result, what, ok=(200, 201, 204)):
    code, data = result
    if code not in ok:
        raise RuntimeError(f"{what}: HTTP {code} {data}")
    return data


def wait_forgejo():
    for _ in range(90):
        try:
            with urllib.request.urlopen(f"{FORGEJO}/api/healthz", timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("Forgejo did not become healthy")


def token_works(token):
    # 401 means the token is unknown or revoked. A narrowly scoped token (for
    # example read:repository only) gets 403 from /user, which still proves it
    # is valid.
    code, _ = fj("GET", "/user", token=token)
    return code in (200, 403)


# ---------------------------------------------------------------- modes
def admin_secret():
    if get_secret("forgejo", "forgejo-admin"):
        log("forgejo/forgejo-admin exists")
        return
    put_secret("forgejo", "forgejo-admin",
               {"username": "box1-admin", "password": secrets.token_urlsafe(32)})


def ensure_org(admin):
    code, _ = fj("GET", f"/orgs/{ORG}", auth=admin)
    if code == 404:
        must(fj("POST", "/orgs", {"username": ORG, "visibility": "private",
                                  "repo_admin_change_team_access": False}, auth=admin), "create org")
        log(f"org {ORG} created")
    teams = {t["name"]: t for t in must(fj("GET", f"/orgs/{ORG}/teams", auth=admin), "list teams")}
    for name, perm, create in (("writers", "write", True), ("readers", "read", False),
                               ("ci-admins", "admin", False)):
        if name not in teams:
            body = {"name": name, "permission": perm, "includes_all_repositories": True,
                    "can_create_org_repo": create, "units": TEAM_UNITS,
                    "units_map": {u: perm for u in TEAM_UNITS}}
            teams[name] = must(fj("POST", f"/orgs/{ORG}/teams", body, auth=admin), f"team {name}")
            log(f"team {name} created")
    return teams


def ensure_account(admin, user, team, scopes, teams):
    code, _ = fj("GET", f"/users/{user}", auth=admin)
    password = secrets.token_urlsafe(32)
    if code == 404:
        must(fj("POST", "/admin/users", {"username": user, "email": f"{user}@forgejo.invalid",
                                         "password": password, "must_change_password": False,
                                         "visibility": "private"}, auth=admin), f"create {user}")
        log(f"user {user} created")
    else:
        # A fresh password each run: it is only used here, to mint a token.
        must(fj("PATCH", f"/admin/users/{user}", {"login_name": user, "source_id": 0,
                                                 "password": password,
                                                 "must_change_password": False}, auth=admin),
             f"reset {user}")
    must(fj("PUT", f"/teams/{teams[team]['id']}/members/{user}", auth=admin), f"{user} -> {team}")
    return password


def mint_token(user, password, scopes):
    name = f"box1-{int(time.time())}"
    data = must(fj("POST", f"/users/{user}/tokens", {"name": name, "scopes": scopes},
                   auth=(user, password)), f"token for {user}")
    # Drop older bootstrap tokens so only the current one is valid.
    for t in must(fj("GET", f"/users/{user}/tokens", auth=(user, password)), "list tokens"):
        if t["name"].startswith("box1-") and t["name"] != name:
            fj("DELETE", f"/users/{user}/tokens/{t['id']}", auth=(user, password))
    return data["sha1"]


def consumer_secrets():
    """Where each account's token lives, and how to read it back."""
    ci, rhdh, argo = CI_NS, P["RHDH_NAMESPACE"], P["ARGOCD_NAMESPACE"]
    dev = P.get("DEVSPACES_USER", "box1-dev")
    return {
        "rhdh-bot": (rhdh, "developer-hub-forgejo-secrets", "FORGEJO_TOKEN",
                     lambda u, t: ({"FORGEJO_USERNAME": u, "FORGEJO_TOKEN": t}, {}, {})),
        "pac-bot": (ci, "forgejo-pac", "provider.token", None),  # webhook secret added below
        "promote-bot": (ci, "forgejo-promote", "token",
                        lambda u, t: ({"username": u, "token": t}, {}, {})),
        "argocd-bot": (argo, "forgejo-repo-creds", "password",
                       lambda u, t: ({"type": "git", "url": f"https://{HOST}/{ORG}",
                                      "username": u, "password": t},
                                     {"argocd.argoproj.io/secret-type": "repo-creds"}, {})),
        # Dev Spaces namespaces are not GitOps-managed: the developer copies this
        # into a git-credentials Secret in their own namespace (see README).
        dev: ("forgejo", "forgejo-dev-token", "token",
              lambda u, t: ({"username": u, "token": t}, {}, {})),
    }


def ensure_gitops_repo(admin):
    code, _ = fj("GET", f"/repos/{ORG}/{GITOPS_REPO}", auth=admin)
    if code == 404:
        must(fj("POST", f"/orgs/{ORG}/repos", {"name": GITOPS_REPO, "private": True,
                                               "auto_init": True, "default_branch": "main",
                                               "description": "Forgejo proof GitOps target"},
                auth=admin), "create gitops repo")
        log(f"repo {ORG}/{GITOPS_REPO} created")
    seed_repo(admin, GITOPS_REPO)
    ensure_protection(admin, GITOPS_REPO)


def seed_repo(admin, repo):
    """Add seed files that are missing. Existing files are never overwritten."""
    if not os.path.isdir(SEED_DIR):
        return
    files = []
    for key in sorted(os.listdir(SEED_DIR)):
        if key.startswith(".."):
            continue  # ConfigMap volume internals
        path = key.replace("__", "/")
        code, _ = fj("GET", f"/repos/{ORG}/{repo}/contents/{urllib.parse.quote(path)}?ref=main", auth=admin)
        if code == 404:
            content = open(os.path.join(SEED_DIR, key), "rb").read()
            files.append({"operation": "create", "path": path,
                          "content": base64.b64encode(content).decode()})
    if files:
        # Seeding happens before branch protection exists on a new repo; on an
        # existing repo the admin account is allowed to push (see protection).
        must(fj("POST", f"/repos/{ORG}/{repo}/contents",
                {"branch": "main", "message": "Seed from forgejo-bootstrap", "files": files},
                auth=admin), "seed files")
        log(f"seeded {len(files)} file(s) into {repo}")


def ensure_protection(admin, repo):
    contexts = [c.strip() for c in P.get("GITOPS_REQUIRED_CONTEXTS", "").split(",") if c.strip()]
    body = {
        "rule_name": "main",
        # No direct pushes by anyone but the admin account (break-glass, seeding).
        "enable_push": True, "enable_push_whitelist": True,
        "push_whitelist_usernames": ["box1-admin"],
        "enable_merge_whitelist": True,
        "merge_whitelist_usernames": ["promote-bot", "box1-admin"],
        "enable_status_check": bool(contexts), "status_check_contexts": contexts,
        "block_on_outdated_branch": True,
        "block_on_rejected_reviews": True,
        "required_approvals": 0,
    }
    existing = {b["rule_name"] for b in must(fj("GET", f"/repos/{ORG}/{repo}/branch_protections", auth=admin), "list protections")}
    if "main" in existing:
        body.pop("rule_name")
        must(fj("PATCH", f"/repos/{ORG}/{repo}/branch_protections/main", body, auth=admin), "update protection")
    else:
        must(fj("POST", f"/repos/{ORG}/{repo}/branch_protections", body, auth=admin), "create protection")
    log(f"branch protection on {repo}:main (required contexts: {contexts or 'none yet'})")


def ensure_webhook(admin, secret):
    url = P["PAC_WEBHOOK_URL"]
    body = {"type": "gitea", "active": True, "branch_filter": "*",
            "events": ["push", "pull_request", "pull_request_sync", "issue_comment",
                       "pull_request_comment"],
            "config": {"url": url, "content_type": "json", "secret": secret}}
    hooks = must(fj("GET", f"/orgs/{ORG}/hooks", auth=admin), "list hooks")
    match = [h for h in hooks if h.get("config", {}).get("url") == url]
    if match:
        must(fj("PATCH", f"/orgs/{ORG}/hooks/{match[0]['id']}",
                {k: body[k] for k in ("active", "branch_filter", "events", "config")}, auth=admin),
             "update hook")
    else:
        must(fj("POST", f"/orgs/{ORG}/hooks", body, auth=admin), "create hook")
    log(f"org webhook -> {url}")


def bootstrap():
    wait_forgejo()
    a = get_secret("forgejo", "forgejo-admin")
    admin = (a["username"], a["password"])
    must(fj("GET", "/user", auth=admin), "admin login")
    teams = ensure_org(admin)
    where = consumer_secrets()

    for user, (team, scopes) in ACCOUNTS.items():
        ns, name, key, build = where[user]
        current = get_secret(ns, name) or {}
        have = current.get(key)
        password = ensure_account(admin, user, team, scopes, teams)
        if have and token_works(have):
            log(f"{user}: token in {ns}/{name} still valid")
            token = have
        else:
            token = mint_token(user, password, scopes)
            log(f"{user}: new token")
        if user == "pac-bot":
            webhook = current.get("webhook.secret") or secrets.token_urlsafe(32)
            put_secret(ns, name, {"provider.token": token, "webhook.secret": webhook})
            ensure_webhook(admin, webhook)
        elif token != have:
            data, labels, ann = build(user, token)
            put_secret(ns, name, data, labels, ann)

    ensure_gitops_repo(admin)
    log("done")


if __name__ == "__main__":
    {"admin-secret": admin_secret, "bootstrap": bootstrap}[sys.argv[1]]()
