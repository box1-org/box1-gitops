"""Small TLS-verified RHTPA API helper; tokens stay in process memory."""
import base64,json,subprocess,urllib.request,urllib.parse,urllib.error
BASE='https://tpa.apps.ocp.box1.org'
def ci_token():
 s=json.loads(subprocess.check_output(['kubectl','get','secret','rhtpa-ci','-n','trusted-profile-analyzer','-o','json']))['data']
 s={k:base64.b64decode(v).decode() for k,v in s.items()}
 req=urllib.request.Request(s['issuer-url']+'/protocol/openid-connect/token',data=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':s['client-id'],'client_secret':s['client-secret']}).encode())
 with urllib.request.urlopen(req) as r:return json.load(r)['access_token']
def request(method,path,token,data=None,content_type='application/json'):
 headers={'Content-Type':content_type}
 if token:headers['Authorization']='Bearer '+token
 req=urllib.request.Request(BASE+path,data=data,headers=headers,method=method)
 try:
  with urllib.request.urlopen(req,timeout=120) as r:return r.status,r.read()
 except urllib.error.HTTPError as e:return e.code,e.read()
if __name__=='__main__':
 t=ci_token()
 for method,path,data in [('GET','/api/v3/sbom',None),('GET','/api/v3/importer',None),('POST','/api/v3/advisory',b'{}')]:
  code,body=request(method,path,t,data);print(method,path,code,body[:300].decode())
