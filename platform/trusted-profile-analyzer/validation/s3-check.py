#!/usr/bin/env python3
"""Verify dedicated S3 access, cross-bucket denial, and optional local object backup."""
import argparse,base64,datetime,hashlib,hmac,json,pathlib,subprocess,urllib.parse,urllib.request,urllib.error,xml.etree.ElementTree as ET
p=argparse.ArgumentParser();p.add_argument('--backup-dir');a=p.parse_args()
ns='trusted-profile-analyzer';name='rhtpa-documents'
def get(kind):return json.loads(subprocess.check_output(['kubectl','get',kind,name,'-n',ns,'-o','json']))['data']
config=get('configmap');keys={k:base64.b64decode(v).decode() for k,v in get('secret').items()}
endpoint='https://s3-openshift-storage.apps.ocp.box1.org';host=urllib.parse.urlparse(endpoint).netloc
bucket=config['BUCKET_NAME'];region='us-east-1'
def request(bucket,key='',params=None):
 now=datetime.datetime.utcnow();stamp=now.strftime('%Y%m%dT%H%M%SZ');date=now.strftime('%Y%m%d')
 path='/'+urllib.parse.quote(bucket,safe='')+'/'+urllib.parse.quote(key,safe='/~')
 query=urllib.parse.urlencode(sorted((params or {}).items()),quote_via=urllib.parse.quote)
 sha=hashlib.sha256(b'').hexdigest();headers=f'host:{host}\nx-amz-content-sha256:{sha}\nx-amz-date:{stamp}\n';signed='host;x-amz-content-sha256;x-amz-date'
 canonical='\n'.join(['GET',path,query,headers,signed,sha]);scope=f'{date}/{region}/s3/aws4_request';tosign='\n'.join(['AWS4-HMAC-SHA256',stamp,scope,hashlib.sha256(canonical.encode()).hexdigest()])
 def sign(k,s):return hmac.new(k,s.encode(),hashlib.sha256).digest()
 k=sign(('AWS4'+keys['AWS_SECRET_ACCESS_KEY']).encode(),date)
 for s in [region,'s3','aws4_request']:k=sign(k,s)
 signature=hmac.new(k,tosign.encode(),hashlib.sha256).hexdigest()
 auth=f'AWS4-HMAC-SHA256 Credential={keys["AWS_ACCESS_KEY_ID"]}/{scope}, SignedHeaders={signed}, Signature={signature}'
 req=urllib.request.Request(endpoint+path+('?' +query if query else ''),headers={'Authorization':auth,'x-amz-date':stamp,'x-amz-content-sha256':sha})
 try:
  with urllib.request.urlopen(req,timeout=120) as r:return r.status,r.read()
 except urllib.error.HTTPError as e:return e.code,e.read()
objects=[];continuation=None
while True:
 params={'list-type':'2'}
 if continuation:params['continuation-token']=continuation
 code,raw=request(bucket,params=params);assert code==200,(code,raw[:200]);tree=ET.fromstring(raw);xmlns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
 objects += [x.text for x in tree.findall('s:Contents/s:Key',xmlns)]
 continuation=tree.findtext('s:NextContinuationToken',namespaces=xmlns)
 if not continuation:break
print('Dedicated bucket list: HTTP 200, objects:',len(objects))
code,_=request('first.bucket',params={'list-type':'2'});assert code==403,code;print('Unrelated first.bucket: HTTP 403')
manifest=[]
for key in objects:
 code,raw=request(bucket,key);assert code==200
 entry={'key':key,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()};manifest.append(entry)
 if a.backup_dir:
  root=pathlib.Path(a.backup_dir);root.mkdir(parents=True,exist_ok=True);filename=hashlib.sha256(key.encode()).hexdigest()+'.object';(root/filename).write_bytes(raw);entry['file']=filename
if a.backup_dir:(pathlib.Path(a.backup_dir)/'manifest.json').write_text(json.dumps({'bucket':bucket,'objects':manifest},indent=2)+'\n')
print('Verified full object downloads:',len(manifest));print('SBOM object integrity:',any(x['sha256']=='9b9d0f23dcbb837d6b1c7b89afea216f34914ff2411c5d9c5c7b336f1eac2714' for x in manifest))
