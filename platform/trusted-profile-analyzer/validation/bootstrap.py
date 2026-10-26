#!/usr/bin/env python3
"""Provision out-of-Git database and OIDC credentials. Never print secrets."""
import base64,json,secrets,subprocess,urllib.request,urllib.parse
NS='trusted-profile-analyzer'
ISSUER='https://keycloak.apps.ocp.box1.org/auth'
def get(kind,name,namespace=NS):
 return json.loads(subprocess.check_output(['kubectl','-n',namespace,'get',kind,name,'-o','json']))
def secret(name,data):
 subprocess.run(['kubectl','apply','--server-side','--field-manager=box1-rhtpa-bootstrap','-f','-'],input=json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':NS},'type':'Opaque','stringData':data}).encode(),check=True)
def exists(name):
 return subprocess.run(['kubectl','-n',NS,'get','secret',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
if not exists('rhtpa-database'):
 secret('rhtpa-database',{'password':secrets.token_urlsafe(36),'admin-password':secrets.token_urlsafe(36)})
admin={k:base64.b64decode(v).decode() for k,v in get('secret','credential-box1-keycloak','keycloak')['data'].items()}
form=urllib.parse.urlencode({'grant_type':'password','client_id':'admin-cli','username':admin['ADMIN_USERNAME'],'password':admin['ADMIN_PASSWORD']}).encode()
with urllib.request.urlopen(ISSUER+'/realms/master/protocol/openid-connect/token',data=form) as r: token=json.load(r)['access_token']
def api(method,path,data=None):
 req=urllib.request.Request(ISSUER+'/admin/realms/box1/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req) as r:
  raw=r.read();return json.loads(raw) if raw else None
for name,public in [('rhtpa-frontend',True),('rhtpa-ci',False)]:
 matches=api('GET','clients?clientId='+name)
 client={'clientId':name,'name':'Box1 RHTPA '+('browser' if public else 'CI ingestion'),'enabled':True,'protocol':'openid-connect','publicClient':public,'standardFlowEnabled':public,'implicitFlowEnabled':False,'directAccessGrantsEnabled':False,'serviceAccountsEnabled':not public,'fullScopeAllowed':False,'redirectUris':['https://tpa.apps.ocp.box1.org/*'] if public else [],'webOrigins':['https://tpa.apps.ocp.box1.org'] if public else [],'defaultClientScopes':['profile','email','roles'] if public else [],'optionalClientScopes':[], 'attributes':{'pkce.code.challenge.method':'S256'} if public else {},'protocolMappers':[{'name':'audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper','consentRequired':False,'config':{'included.client.audience':name,'access.token.claim':'true','id.token.claim':'false'}}]}
 if matches:
  cid=matches[0]['id'];api('PUT','clients/'+cid,client)
 else:
  api('POST','clients',client);cid=api('GET','clients?clientId='+name)[0]['id']
 if not public:
  value=api('GET','clients/'+cid+'/client-secret')['value']
  secret('rhtpa-ci',{'client-id':name,'client-secret':value,'issuer-url':ISSUER+'/realms/box1'})
roles=api('GET','roles')
if not any(r['name']=='rhtpa-admin' for r in roles):api('POST','roles',{'name':'rhtpa-admin','description':'RHTPA document and importer administration'})
role=api('GET','roles/rhtpa-admin')
users=api('GET','users?username=mike&exact=true')
if len(users)!=1:raise SystemExit('Expected the existing mike account; clients created, role assignment incomplete.')
api('POST','users/'+users[0]['id']+'/role-mappings/realm',[role])
# Explicitly expose this one realm role to the dedicated browser client.
front=api('GET','clients?clientId=rhtpa-frontend')[0]
api('POST','clients/'+front['id']+'/scope-mappings/realm',[role])
print('Database Secret, dedicated Keycloak clients, CI Secret and mike RHTPA role provisioned; no credentials printed.')
