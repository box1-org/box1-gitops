#!/usr/bin/env python3
"""Provision Secret-backed connection material without printing credential values.
Requires existing cluster administration access only for bootstrap, never for Hub runtime.
Run after kubernetes-access.yaml and the GitOps account configuration are reconciled.
Use --rotate-argocd to replace the dedicated account token (90 day lifetime).
"""
import base64
import json
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone


def kubectl(*args, payload=None):
    result = subprocess.run(['kubectl', *args], input=json.dumps(payload) if payload else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('kubectl operation failed: ' + ' '.join(args[:4]))
    return result.stdout


def get(kind, name, namespace):
    return json.loads(kubectl('-n', namespace, 'get', kind, name, '-o', 'json'))


def apply(obj):
    if obj['kind'] == 'Secret':
        # Avoid putting stringData in a last-applied metadata annotation.
        kubectl('apply', '--server-side', '--force-conflicts',
                '--field-manager=developer-hub-credentials', '-f', '-', payload=obj)
    else:
        kubectl('apply', '-f', '-', payload=obj)


def provision():
    ingress = get('configmap', 'default-ingress-cert', 'openshift-config-managed')['data']['ca-bundle.crt']
    # Public CA material is cluster-derived and kept out of source, allowing rotation.
    apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {
        'name': 'developer-hub-platform-trust', 'namespace': 'rhdh'},
        'data': {'ca-bundle.crt': ingress}})
    token_secret = get('secret', 'developer-hub-kubernetes-token', 'rhdh')
    assert token_secret.get('data', {}).get('token'), 'ServiceAccount token not populated yet'
    existing = json.loads(kubectl('-n', 'rhdh', 'get', 'secret',
                          'developer-hub-platform-secrets', '--ignore-not-found', '-o', 'json') or '{}')
    if existing.get('data', {}).get('ARGOCD_AUTH_TOKEN') and '--rotate-argocd' not in sys.argv:
        print('Trusted CA refreshed; existing dedicated Argo CD token retained.')
        return
    host = get('route', 'openshift-gitops-server', 'openshift-gitops')['spec']['host']
    context = ssl.create_default_context(cadata=ingress)
    password = base64.b64decode(get('secret', 'openshift-gitops-cluster', 'openshift-gitops')['data']['admin.password']).decode()

    def request(path, body, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request('https://' + host + '/api/v1/' + path,
                                     data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            return json.load(response)

    bootstrap = request('session', {'username': 'admin', 'password': password})['token']
    import uuid
    token_id = 'developer-hub-' + uuid.uuid4().hex[:12]
    token = request('account/developer-hub/token', {'expiresIn': 90 * 86400, 'id': token_id}, bootstrap)['token']
    apply({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque', 'metadata': {
        'name': 'developer-hub-platform-secrets', 'namespace': 'rhdh',
        'annotations': {'box1.org/argocd-token-id': token_id,
                        'box1.org/created-at': datetime.now(timezone.utc).isoformat()}},
        'stringData': {'ARGOCD_AUTH_TOKEN': token}})
    print('Dedicated read-only Argo CD token provisioned (expires in 90 days).')


if __name__ == '__main__':
    provision()
