"""Mirror every non-archived GitHub box1-org repository into GitLab.

For each repository: branches and tags are copied exactly (force-updated,
and branches/tags deleted on GitHub are deleted on GitLab). Pull request refs,
issues and PRs are not copied. Target: private projects in the GitLab group
MIRROR_GROUP, created on first sync. The mirror projects are read-only by
convention: only mirror-bot is a member, and every run overwrites them.

Environment:
  GITHUB_ORG, GITLAB_URL, MIRROR_GROUP, GITLAB_TOKEN (mirror-bot)
  GITHUB_TOKEN (optional; read-only, needed for private repositories)
Standard library + git. Tokens never appear in logs or on the command line.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ORG = os.environ["GITHUB_ORG"]
GL = os.environ["GITLAB_URL"].rstrip("/")
GROUP = os.environ["MIRROR_GROUP"]
GL_TOKEN = os.environ["GITLAB_TOKEN"]
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
SKIP = {s.strip() for s in os.environ.get("SKIP_REPOS", "").split(",") if s.strip()}


def log(msg):
    print(f"[mirror] {msg}", flush=True)


def http(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None, e.headers
        except ValueError:
            return e.code, raw.decode(errors="replace")[:300], e.headers


def gh_repos():
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GH_TOKEN:
        headers["Authorization"] = f"Bearer {GH_TOKEN}"
    repos, page = [], 1
    while True:
        code, data, hdrs = http(f"https://api.github.com/orgs/{ORG}/repos?type=all&per_page=100&page={page}",
                                headers=headers)
        if code != 200:
            sys.exit(f"list GitHub repos: HTTP {code} {data} (rate limit remaining: {hdrs.get('X-RateLimit-Remaining')})")
        repos += data
        if len(data) < 100:
            return repos
        page += 1


def gl(method, path, body=None):
    code, data, _ = http(f"{GL}/api/v4{path}", method, body,
                         {"PRIVATE-TOKEN": GL_TOKEN, "Content-Type": "application/json"})
    return code, data


def must(res, what, ok=(200, 201, 204)):
    code, data = res
    if code not in ok:
        raise RuntimeError(f"{what}: HTTP {code} {data}")
    return data


def ensure_project(group_id, repo):
    path = f"{GROUP}/{repo['name']}"
    code, proj = gl("GET", f"/projects/{urllib.parse.quote(path, safe='')}")
    desc = f"Mirror of github.com/{ORG}/{repo['name']}. Read-only: overwritten by the github-mirror CronJob."
    if code == 404:
        proj = must(gl("POST", "/projects", {"name": repo["name"], "path": repo["name"], "namespace_id": group_id,
                                             "visibility": "private", "description": desc,
                                             "initialize_with_readme": False}), f"create {path}")
        log(f"{repo['name']}: project created")
    elif code != 200:
        raise RuntimeError(f"read {path}: HTTP {code} {proj}")
    return proj


def git(*args, cwd=None, env=None):
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        # git prints URLs without credentials (they come from the helper), so stderr is safe to show.
        raise RuntimeError(f"git {args[0]}: {r.stderr.strip()[-400:]}")
    return r.stdout


def sync(repo, proj, workdir, env):
    name = repo["name"]
    d = os.path.join(workdir, name + ".git")
    git("init", "-q", "--bare", d, env=env)
    git("remote", "add", "github", f"https://github.com/{ORG}/{name}.git", cwd=d, env=env)
    git("remote", "add", "gitlab", f"{GL}/{GROUP}/{name}.git", cwd=d, env=env)
    git("fetch", "-q", "--prune", "github", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*", cwd=d, env=env)
    heads = git("for-each-ref", "--format=%(refname)", "refs/heads", cwd=d, env=env).split()
    tags = git("for-each-ref", "--format=%(refname)", "refs/tags", cwd=d, env=env).split()
    if not heads:
        log(f"{name}: empty on GitHub, nothing to push")
        return
    # Protected branches would refuse force-updates and deletions: the mirror
    # is not a place to protect anything, GitHub is the source of truth.
    for pb in must(gl("GET", f"/projects/{proj['id']}/protected_branches"), "list protected") or []:
        gl("DELETE", f"/projects/{proj['id']}/protected_branches/{urllib.parse.quote(pb['name'], safe='')}")
    out = subprocess.run(["git", "push", "--porcelain", "--prune", "gitlab",
                          "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"],
                         cwd=d, env=env, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f"git push: {out.stderr.strip()[-400:]}")
    changed = [l for l in out.stdout.splitlines() if l[:1] in ("+", "*", "-", " ") and "\t" in l and not l.startswith("=")]
    default = repo.get("default_branch")
    if default and proj.get("default_branch") != default:
        must(gl("PUT", f"/projects/{proj['id']}", {"default_branch": default}), "set default branch")
    log(f"{name}: {len(heads)} branches, {len(tags)} tags, {len(changed)} ref update(s)")


def main():
    started = time.time()
    code, group = gl("GET", f"/groups/{urllib.parse.quote(GROUP, safe='')}")
    if code != 200:
        sys.exit(f"GitLab group {GROUP}: HTTP {code} {group} (created by the gitlab bootstrap)")
    repos = [r for r in gh_repos() if not r.get("archived") and r["name"] not in SKIP]
    log(f"{len(repos)} non-archived repositories in github.com/{ORG}")

    workdir = tempfile.mkdtemp(dir="/work")
    # Credentials only through a helper script reading the environment.
    helper = os.path.join(workdir, "credential-helper")
    with open(helper, "w") as f:
        f.write('#!/bin/sh\n[ "$1" = get ] || exit 0\nwhile read -r l; do case "$l" in host=*) h=${l#host=};; esac; done\n'
                'case "$h" in\n  github.com) [ -n "$GITHUB_TOKEN" ] && printf "username=x-access-token\\npassword=%s\\n" "$GITHUB_TOKEN";;\n'
                '  *) printf "username=mirror-bot\\npassword=%s\\n" "$GITLAB_TOKEN";;\nesac\n')
    os.chmod(helper, 0o700)
    env = {**os.environ, "HOME": workdir, "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": helper}

    ok, skipped, failed = [], [], []
    for repo in repos:
        if repo.get("private") and not GH_TOKEN:
            log(f"{repo['name']}: private on GitHub and no GITHUB_TOKEN: skipped")
            skipped.append(repo["name"])
            continue
        try:
            proj = ensure_project(group["id"], repo)
            sync(repo, proj, workdir, env)
            ok.append(repo["name"])
        except Exception as e:  # keep going; report at the end
            log(f"{repo['name']}: FAILED {e}")
            failed.append(repo["name"])
    log(f"done in {int(time.time() - started)}s: {len(ok)} synced, {len(skipped)} skipped {skipped}, "
        f"{len(failed)} failed {failed}")
    if failed:
        sys.exit(1)


main()
