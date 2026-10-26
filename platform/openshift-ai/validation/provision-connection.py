#!/usr/bin/env python3
"""Copy dedicated OBC credentials into an AI connection without logging secrets."""
import base64
import json
import subprocess

NAMESPACE = 'box1-ai-test'

def get(kind, name):
    return json.loads(subprocess.check_output(
        ['kubectl', '-n', NAMESPACE, 'get', kind, name, '-o', 'json']))

obc = get('objectbucketclaim', 'box1-ai-test')
if obc.get('status', {}).get('phase') != 'Bound':
    raise SystemExit('Wait until the dedicated ObjectBucketClaim is Bound.')
config = get('configmap', 'box1-ai-test')['data']
secret = get('secret', 'box1-ai-test')['data']
values = {
    'AWS_ACCESS_KEY_ID': base64.b64decode(secret['AWS_ACCESS_KEY_ID']).decode(),
    'AWS_SECRET_ACCESS_KEY': base64.b64decode(secret['AWS_SECRET_ACCESS_KEY']).decode(),
    'AWS_S3_ENDPOINT': 'https://s3-openshift-storage.apps.ocp.box1.org',
    'AWS_S3_BUCKET': config['BUCKET_NAME'],
    'AWS_DEFAULT_REGION': 'us-east-1',
}
connection = {
    'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
    'metadata': {
        'name': 'noobaa-connection', 'namespace': NAMESPACE,
        'labels': {'opendatahub.io/dashboard': 'true', 'opendatahub.io/managed': 'true'},
        'annotations': {
            'openshift.io/display-name': 'Box1 dedicated NooBaa bucket',
            'opendatahub.io/connection-type': 's3',
            'opendatahub.io/connection-type-ref': 's3',
            'opendatahub.io/connection-type-protocol': 's3',
            'serving.kserve.io/s3-endpoint': 's3-openshift-storage.apps.ocp.box1.org',
            'serving.kserve.io/s3-usehttps': '1',
            'serving.kserve.io/s3-region': 'us-east-1',
            'serving.kserve.io/s3-useanoncredential': 'false',
        },
    },
    'stringData': values,
}
# Server-side apply avoids storing plaintext credentials in last-applied annotations.
subprocess.run(['kubectl', 'apply', '--server-side', '--field-manager=box1-ai-connection', '-f', '-'],
               input=json.dumps(connection).encode(), check=True)
print('Connection provisioned from dedicated OBC credentials; values were not printed.')
