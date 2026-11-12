"""Minimal in-cluster Kubernetes client for RHDP credential reconcilers.

Never log a Secret value: helpers report names and keys only.
"""
import base64
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
API = "https://kubernetes.default.svc"
NAMESPACE = os.environ.get("POD_NAMESPACE", "")
SYSTEM_NAMESPACE = os.environ.get("BOX1_SYSTEM_NAMESPACE", "box1-rhdp-system")
INPUTS_SECRET = os.environ.get("BOX1_INPUTS_SECRET", "box1-rhdp-inputs")
MANAGER = "box1-rhdp"
LABELS = {"app.kubernetes.io/part-of": "box1-rhdp"}

_token = None
_ctx = None
problems = []


def _auth():
    global _token, _ctx
    if _token is None:
        with open(SA + "/token") as f:
            _token = f.read().strip()
        _ctx = ssl.create_default_context(cafile=SA + "/ca.crt")
    return _token, _ctx


def call(method, path, body=None, content_type="application/json"):
    """Return (status, parsed JSON or None). 404 is not an error."""
    token, ctx = _auth()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 404, None
        raise RuntimeError(f"{method} {path}: HTTP {e.code} {e.read()[:300]!r}") from None


def _decode(obj):
    return {k: base64.b64decode(v).decode() for k, v in (obj.get("data") or {}).items()}


def get_secret(namespace, name):
    """Decoded data, or None when the Secret does not exist (or is not readable yet)."""
    status, obj = call("GET", f"/api/v1/namespaces/{namespace}/secrets/{name}")
    return None if status == 404 else _decode(obj)


def get_configmap(namespace, name):
    status, obj = call("GET", f"/api/v1/namespaces/{namespace}/configmaps/{name}")
    return None if status == 404 else (obj.get("data") or {})


def inputs():
    """Keys of the box1-rhdp-inputs Secret ({} when it does not exist)."""
    try:
        return get_secret(SYSTEM_NAMESPACE, INPUTS_SECRET) or {}
    except RuntimeError as e:
        missing(f"cannot read {SYSTEM_NAMESPACE}/{INPUTS_SECRET}: {e}")
        return {}


def _apply(kind, namespace, name, body):
    plural = {"Secret": "secrets", "ConfigMap": "configmaps"}[kind]
    q = urllib.parse.urlencode({"fieldManager": MANAGER, "force": "true"})
    call("PATCH", f"/api/v1/namespaces/{namespace}/{plural}/{name}?{q}", body,
         "application/apply-patch+yaml")


def apply_secret(namespace, name, data, type_="Opaque"):
    """Server-Side Apply: no last-applied annotation carries the values."""
    body = {"apiVersion": "v1", "kind": "Secret", "type": type_,
            "metadata": {"name": name, "namespace": namespace, "labels": LABELS},
            "data": {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}}
    _apply("Secret", namespace, name, body)
    print(f"applied secret {namespace}/{name} keys={sorted(data)}")


def apply_configmap(namespace, name, data):
    body = {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": namespace, "labels": LABELS},
            "data": data}
    _apply("ConfigMap", namespace, name, body)
    print(f"applied configmap {namespace}/{name} keys={sorted(data)}")


def generated(namespace, name, keys, extra=None, nbytes=36):
    """Create keys once with random values; keep existing values; merge extra."""
    current = get_secret(namespace, name) or {}
    data = dict(current)
    for k in keys:
        if not data.get(k):
            data[k] = secrets.token_urlsafe(nbytes)
    data.update(extra or {})
    if data != current:
        apply_secret(namespace, name, data)
    else:
        print(f"secret {namespace}/{name} unchanged")
    return data


def require(source, keys, why):
    """Values of keys from a dict, or None (reported) when any is missing."""
    absent = [k for k in keys if not source.get(k)]
    if absent:
        missing(f"{why}: missing {', '.join(absent)}")
        return None
    return {k: source[k] for k in keys}


def missing(message):
    problems.append(message)
    print("WAITING: " + message)


def finish():
    """Exit 0 even when inputs are missing; the CronJob retries."""
    if problems:
        print(f"{len(problems)} item(s) waiting; will retry on the next schedule")
    else:
        print("all credentials reconciled")
    sys.exit(0)
