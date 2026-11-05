#!/usr/bin/env python3
"""Keep the onboarding plugin delivered only as a digest-pinned OCI artifact.

  check-onboarding-runtime.py <checkout>              static checks on a box1-gitops tree
  check-onboarding-runtime.py <checkout> --registry   also reads the artifact from the registry
  check-onboarding-runtime.py <checkout> --live       also checks the cluster, after an Argo sync
  check-onboarding-runtime.py --self-test             proves each static check can fail

--registry reads REGISTRY_TOKEN, or the pod's service account token. --live uses `oc get --raw`
with the current login.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

REGISTRY = 'registry.apps.ocp.box1.org'
REPOSITORY = 'box1-plugins/box1-onboarding-plugin'
PLUGIN_PATH = 'box1-scaffolder-onboarding'
PACKAGE = 'box1-scaffolder-onboarding-dynamic'
HUB = 'platform/developer-hub'
DIGEST = r'sha256:[a-f0-9]{64}'
RUNTIME = re.compile(r'^oci://%s/%s@(%s)!(\S+)$' % (re.escape(REGISTRY), re.escape(REPOSITORY), DIGEST))
PACKAGE_LINE = re.compile(r'^\s*-\s*package:\s*(\S+)\s*$', re.M)
PLUGIN_NAMES = re.compile(r'box1-onboarding-plugin|box1-scaffolder-onboarding')
SOURCE_MARKERS = ('box1:development:', 'box1-development-onboarding')
TARBALL = re.compile(r'\.(tgz|tar|tar\.gz)$')
TEXT_SUFFIXES = {'.yaml', '.yml', '.json', '.py', '.cjs', '.js', '.ts', '.sh'}
SKIP_DIRECTORIES = {'.git', 'node_modules'}
THIS_FILE = HUB + '/scripts/check-onboarding-runtime.py'
RETIRED_COPY = HUB + '/onboarding/plugin/'


def read_tree(root):
    files = {}
    for path in pathlib.Path(root).rglob('*'):
        if not path.is_file() or SKIP_DIRECTORIES.intersection(path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix in TEXT_SUFFIXES:
            files[relative] = path.read_text(errors='replace')
        else:
            files[relative] = ''
    return files


def workload_section(backstage):
    return backstage.split('database:')[0]


def static_errors(files):
    errors = []
    dynamic = files.get(HUB + '/dynamic-plugins.yaml', '')
    backstage = files.get(HUB + '/backstage.yaml', '')
    seed = files.get(HUB + '/extensions-seed.yaml', '')
    kustomization = files.get(HUB + '/kustomization.yaml', '')

    definitions = [p for p in PACKAGE_LINE.findall(dynamic + '\n' + seed) if PLUGIN_NAMES.search(p)]
    if len(definitions) != 1:
        errors.append('expected one onboarding plugin definition, found %d: %s' % (len(definitions), definitions))
    digest = None
    for definition in definitions:
        match = RUNTIME.match(definition)
        if not match:
            errors.append('runtime reference must be oci://%s/%s@sha256:<digest>!<path>: %s' % (REGISTRY, REPOSITORY, definition))
            continue
        digest = match.group(1)
        if match.group(2) != PLUGIN_PATH:
            errors.append('plugin path is %s, expected %s' % (match.group(2), PLUGIN_PATH))

    annotation = re.findall(r'box1\.org/onboarding-plugin-digest:\s*(\S+)', backstage)
    if len(annotation) != 1:
        errors.append('expected one rollout digest annotation, found %d' % len(annotation))
    elif digest and annotation[0] != digest:
        errors.append('rollout annotation %s differs from runtime digest %s' % (annotation[0], digest))
    if len(re.findall(r'box1\.org/onboarding-plugin-revision:\s*[a-f0-9]{40}\b', backstage)) != 1:
        errors.append('expected one source revision annotation with a full commit SHA')
    if 'dynamic-plugins-root' not in backstage or 'claimName: dynamic-plugins-root' not in backstage:
        errors.append('the dynamic plugin cache PVC must stay on the workload')

    workload = workload_section(backstage)
    for retired in ('/onboarding-plugin-source', 'onboarding-staged', 'name: onboarding-plugin',
                    'developer-hub-onboarding-plugin', 'onboarding-plugin-sha'):
        if retired in workload:
            errors.append('the RHDH workload references the retired source path: ' + retired)

    for path, content in files.items():
        if path == THIS_FILE:
            continue
        if TARBALL.search(path):
            errors.append('plugin tarball in box1-gitops: ' + path)
        if 'dist-dynamic' in path.split('/'):
            errors.append('dist-dynamic output in box1-gitops: ' + path)
        if path.endswith(('.cjs', '.js', '.ts')) and all(marker in content for marker in SOURCE_MARKERS):
            errors.append('onboarding plugin source in box1-gitops: ' + path)
        if path.endswith('package.json') and '"name": "%s"' % PACKAGE in content:
            errors.append('onboarding plugin package in box1-gitops: ' + path)

    for path in files:
        if path.startswith(RETIRED_COPY):
            errors.append('retired plugin copy still present: ' + path)
    if 'onboarding/plugin/' in kustomization or 'developer-hub-onboarding-plugin' in kustomization:
        errors.append('the source ConfigMap generator is still present')
    if '/onboarding-plugin-source' in seed:
        errors.append('the source staging code is still present in the Extensions adapter')
    return errors, digest


class Registry:
    def __init__(self, token, opener=urllib.request.urlopen):
        self.token, self.bearer, self.opener = token, None, opener

    def get(self, path, accept=None):
        url = 'https://%s/v2/%s/%s' % (REGISTRY, REPOSITORY, path)
        for attempt in (1, 2):
            headers = {'Accept': accept} if accept else {}
            if self.bearer:
                headers['Authorization'] = 'Bearer ' + self.bearer
            try:
                with self.opener(urllib.request.Request(url, headers=headers), timeout=60) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code != 401 or attempt == 2:
                    raise
                self.login(error.headers.get('WWW-Authenticate', ''))

    def login(self, challenge):
        realm = re.search(r'realm="([^"]+)"', challenge).group(1)
        service = re.search(r'service="([^"]+)"', challenge)
        query = urllib.parse.urlencode({'service': service.group(1) if service else '', 'scope': 'repository:%s:pull' % REPOSITORY})
        basic = base64.b64encode(('serviceaccount:' + self.token).encode()).decode()
        request = urllib.request.Request(realm + '?' + query, headers={'Authorization': 'Basic ' + basic})
        with self.opener(request, timeout=60) as response:
            self.bearer = json.load(response)['token']


def artifact_errors(registry, digest, expected_revision):
    errors = []
    try:
        accept = 'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'
        raw = registry.get('manifests/' + digest, accept)
    except urllib.error.HTTPError as error:
        return ['digest %s cannot be read from the registry: HTTP %d' % (digest, error.code)]
    if 'sha256:' + hashlib.sha256(raw).hexdigest() != digest:
        return ['registry manifest does not hash to ' + digest]
    manifest = json.loads(raw)
    config = json.loads(registry.get('blobs/' + manifest['config']['digest']))
    labels = config.get('config', {}).get('Labels', {})
    if labels.get('org.opencontainers.image.revision') != expected_revision:
        errors.append('artifact revision %s differs from GitOps revision %s' % (labels.get('org.opencontainers.image.revision'), expected_revision))
    layer = registry.get('blobs/' + manifest['layers'][0]['digest'])
    with tarfile.open(fileobj=io.BytesIO(layer), mode='r:*') as archive:
        names = {name.lstrip('./') for name in archive.getnames()}
        wanted = PLUGIN_PATH + '/package.json'
        if wanted not in names:
            return errors + ['plugin path %s is not in the artifact' % PLUGIN_PATH]
        member = next(m for m in archive.getmembers() if m.name.lstrip('./') == wanted)
        package = json.load(archive.extractfile(member))
    if package.get('name') != PACKAGE:
        errors.append('artifact package is %s, expected %s' % (package.get('name'), PACKAGE))
    return errors


def kube_get(path):
    return json.loads(subprocess.check_output(['oc', 'get', '--raw', path]))


def cluster_errors(digest, get=kube_get):
    errors = []
    deployment = get('/apis/apps/v1/namespaces/rhdh/deployments/backstage-developer-hub')
    owners = [o.get('kind') for o in deployment['metadata'].get('ownerReferences', [])]
    if owners != ['Backstage']:
        errors.append('the Deployment must be owned by the Backstage CR, found %s' % owners)
    spec = deployment['spec']['template']['spec']
    volumes = {v['name']: v for v in spec['volumes']}
    if volumes.get('dynamic-plugins-registry-auth', {}).get('secret', {}).get('secretName') != 'dynamic-plugins-registry-auth':
        errors.append('the installer has no registry auth volume')
    if volumes.get('dynamic-plugins-root', {}).get('persistentVolumeClaim', {}).get('claimName') != 'dynamic-plugins-root':
        errors.append('the cache PVC is not mounted')
    for retired in ('onboarding-plugin', 'onboarding-staged'):
        if retired in volumes:
            errors.append('the live workload still has volume ' + retired)
    annotations = deployment['spec']['template']['metadata'].get('annotations', {})
    if annotations.get('box1.org/onboarding-plugin-digest') != digest:
        errors.append('the live workload is not at digest ' + digest)
    secret = get('/api/v1/namespaces/rhdh/secrets/dynamic-plugins-registry-auth')
    if 'auth.json' not in secret.get('data', {}):
        errors.append('the registry auth Secret has no auth.json')
    else:
        auths = json.loads(base64.b64decode(secret['data']['auth.json'])).get('auths', {})
        if REGISTRY not in auths:
            errors.append('the registry auth Secret has no entry for ' + REGISTRY)
    application = get('/apis/argoproj.io/v1alpha1/namespaces/openshift-gitops/applications/developer-hub')
    source = application['spec']['source']
    if source.get('repoURL') != 'https://github.com/box1-org/box1-gitops.git' or source.get('path') != HUB:
        errors.append('the developer-hub Application source changed: %s' % source)
    if application['status']['sync']['status'] != 'Synced' or application['status']['health']['status'] != 'Healthy':
        errors.append('developer-hub is %s and %s' % (application['status']['sync']['status'], application['status']['health']['status']))
    return errors


def self_test():
    digest = 'sha256:' + 'a' * 64
    revision = 'b' * 40
    reference = 'oci://%s/%s@%s!%s' % (REGISTRY, REPOSITORY, digest, PLUGIN_PATH)

    def valid():
        return {
            HUB + '/dynamic-plugins.yaml': 'plugins:\n  - package: %s\n    disabled: false\n  - package: ./other\n' % reference,
            HUB + '/backstage.yaml': ('box1.org/onboarding-plugin-digest: %s\nbox1.org/onboarding-plugin-revision: %s\n'
                                      'name: dynamic-plugins-root\nclaimName: dynamic-plugins-root\n') % (digest, revision),
            HUB + '/extensions-seed.yaml': 'plugins:\n  - package: ./dynamic-plugins/dist/x\n',
            HUB + '/kustomization.yaml': 'resources: []\n',
        }

    def edit(path, old, new):
        def apply(files):
            assert old in files[path], old
            files[path] = files[path].replace(old, new)
        return apply

    def add(path, content):
        def apply(files):
            files[path] = content
        return apply

    dynamic, backstage = HUB + '/dynamic-plugins.yaml', HUB + '/backstage.yaml'
    source = "createBackendModule({moduleId:'box1-development-onboarding'});id:'box1:development:onboard'"
    cases = {
        'mutable tag': (edit(dynamic, '@' + digest, ':1.1.0'), 'runtime reference must be'),
        'latest tag': (edit(dynamic, '@' + digest, ':latest'), 'runtime reference must be'),
        'malformed digest': (edit(dynamic, digest, 'sha256:abc'), 'runtime reference must be'),
        'missing plugin path': (edit(dynamic, '!' + PLUGIN_PATH, ''), 'runtime reference must be'),
        'wrong plugin path': (edit(dynamic, '!' + PLUGIN_PATH, '!other'), 'plugin path is other'),
        'other registry': (edit(dynamic, REGISTRY, 'quay.io'), 'runtime reference must be'),
        'local package': (edit(dynamic, reference, './box1-scaffolder-onboarding-dynamic'), 'runtime reference must be'),
        'duplicate definition': (edit(dynamic, './other', reference), 'expected one onboarding plugin definition, found 2'),
        'duplicate in seed': (edit(HUB + '/extensions-seed.yaml', './dynamic-plugins/dist/x', reference), 'found 2'),
        'no definition': (edit(dynamic, reference, './other'), 'found 0'),
        'stale annotation': (edit(backstage, 'digest: ' + digest, 'digest: sha256:' + 'c' * 64), 'differs from runtime digest'),
        'missing revision': (edit(backstage, 'revision: ' + revision, 'revision: main'), 'source revision annotation'),
        'source mount': (edit(backstage, 'name: dynamic', 'mountPath: /onboarding-plugin-source\nname: dynamic'), 'retired source path'),
        'staging volume': (edit(backstage, 'name: dynamic', 'name: onboarding-staged\nname: dynamic'), 'retired source path'),
        'source ConfigMap': (edit(backstage, 'name: dynamic', 'name: developer-hub-onboarding-plugin\nname: dynamic'), 'retired source path'),
        'cache PVC removed': (edit(backstage, 'claimName: dynamic-plugins-root', ''), 'cache PVC'),
        'copied source': (add(HUB + '/copy/index.cjs', source), 'plugin source in box1-gitops'),
        'copied package': (add(HUB + '/x/package.json', '{"name": "%s"}' % PACKAGE), 'plugin package in box1-gitops'),
        'tarball': (add(HUB + '/plugin.tgz', ''), 'tarball'),
        'dist-dynamic': (add(HUB + '/x/dist-dynamic/package.json', '{}'), 'dist-dynamic'),
        'retained copy': (add(HUB + '/onboarding/plugin/index.cjs', source), 'retired plugin copy'),
        'generator': (edit(HUB + '/kustomization.yaml', 'resources: []', 'files:\n  - onboarding/plugin/index.cjs'), 'generator'),
        'staging code': (edit(HUB + '/extensions-seed.yaml', 'plugins:', 'Path("/onboarding-plugin-source")\nplugins:'), 'staging code'),
    }
    failed = []
    errors, found = static_errors(valid())
    if errors or found != digest:
        failed.append('the valid tree failed: %s' % errors)
    for name, (mutate, expected) in cases.items():
        files = valid()
        mutate(files)
        errors, _ = static_errors(files)
        if not any(expected in error for error in errors):
            failed.append('%s: expected %r, got %s' % (name, expected, errors))
    if failed:
        sys.exit('Self-test failed:\n' + '\n'.join(failed))
    print('Self-test passed: %d violations were each rejected.' % len(cases))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('checkout', nargs='?')
    parser.add_argument('--registry', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.checkout:
        parser.error('checkout is required')
    files = read_tree(args.checkout)
    errors, digest = static_errors(files)
    if not errors and (args.registry or args.live):
        token = os.environ.get('REGISTRY_TOKEN') or pathlib.Path('/var/run/secrets/kubernetes.io/serviceaccount/token').read_text()
        revision = re.search(r'box1\.org/onboarding-plugin-revision:\s*(\S+)', files[HUB + '/backstage.yaml']).group(1)
        errors += artifact_errors(Registry(token), digest, revision)
    if not errors and args.live:
        errors += cluster_errors(digest)
    if errors:
        sys.exit('Onboarding plugin runtime check failed:\n- ' + '\n- '.join(errors))
    print('Onboarding plugin runtime check passed: %s (%s)' % (digest, 'live' if args.live else 'registry' if args.registry else 'static'))


if __name__ == '__main__':
    main()
