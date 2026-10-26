#!/usr/bin/env python3
"""TLS-verified CI SBOM upload with immutable provenance labels; no token output."""
import argparse,json,os,pathlib,urllib.parse,urllib.request
p=argparse.ArgumentParser()
for name in ['file','image-digest','source-revision','service','source-repository']:p.add_argument('--'+name,required=True)
a=p.parse_args()
if not a.image_digest.startswith('sha256:') or len(a.image_digest)!=71:raise SystemExit('Supply the exact sha256 image digest.')
if len(a.source_revision)!=40 or any(c not in '0123456789abcdef' for c in a.source_revision):raise SystemExit('Supply the full source commit SHA.')
sbom=json.loads(pathlib.Path(a.file).read_text())
if sbom.get('bomFormat')!='CycloneDX' or sbom.get('specVersion')!='1.5':raise SystemExit('Validated contract: CycloneDX JSON 1.5.')
issuer=os.environ.get('RHTPA_ISSUER','https://keycloak.apps.ocp.box1.org/auth/realms/box1')
form=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':os.environ.get('RHTPA_CLIENT_ID','rhtpa-ci'),'client_secret':os.environ['RHTPA_CLIENT_SECRET']}).encode()
with urllib.request.urlopen(issuer+'/protocol/openid-connect/token',data=form) as r:token=json.load(r)['access_token']
labels={'labels.image-digest':a.image_digest,'labels.source-revision':a.source_revision,'labels.service':a.service,'labels.source-repository':a.source_repository}
url=os.environ.get('RHTPA_URL','https://tpa.apps.ocp.box1.org')+'/api/v3/sbom?format=cyclonedx&cache=Wait&'+urllib.parse.urlencode(labels)
req=urllib.request.Request(url,data=json.dumps(sbom).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(req,timeout=300) as r:
 if r.status!=201:raise SystemExit('Expected HTTP 201')
 print(r.read().decode())
