// Execute inside backstage-backend: kubectl exec -i ... -- node < this-file
// Uses the existing automation backend credential without emitting it.
const assert = require('node:assert/strict');
const base = 'http://localhost:7007/api';
const crypto = require('node:crypto');
const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
const now = Math.floor(Date.now() / 1000);
const payload = Buffer.from(JSON.stringify({ sub: 'backstage-server', iat: now, exp: now + 300 })).toString('base64url');
const unsigned = header + '.' + payload;
const token = unsigned + '.' + crypto.createHmac('sha256', Buffer.from(process.env.BACKEND_SECRET, 'base64url')).update(unsigned).digest('base64url');
async function api(path, body) {
  const response = await fetch(base + path, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  assert(response.ok, `${path}: HTTP ${response.status}: ${await response.clone().text()}`);
  const text = await response.text();
  return text ? JSON.parse(text) : undefined;
}
(async()=>{
for(const [name,host] of [['orders-service','orders-service-dev'],['quarkus-reference','quarkus-reference'],['quarkus-golden-path-smoke','quarkus-golden-path-smoke']]){
 const service=await api('/catalog/entities/by-name/component/default/'+name);
 const provided=service.relations?.find(r=>r.type==='providesApi'&&r.targetRef==='api:default/'+name+'-api');
 assert(provided,name+': missing Provides API relation');
 const entity=await api('/catalog/entities/by-name/api/default/'+name+'-api');
 assert.equal(entity.spec.type,'openapi');
 const definition=require('yaml').parse(entity.spec.definition);
 const route='https://'+host+'.apps.ocp.box1.org';
 assert(definition.servers?.some(s=>s.url===route),name+': incorrect public API server');
 assert(definition.paths['/api/greetings']&&definition.paths['/api/info']);
 const origin='https://developer-hub.apps.ocp.box1.org';
 const response=await fetch(route+'/api/greetings?name=Developer%20Hub',{headers:{Origin:origin}});
 assert(response.ok,name+': endpoint tester request failed');
 assert.equal(response.headers.get('access-control-allow-origin'),origin,name+': CORS not enabled for Hub');
 const denied=await fetch(route+'/api/greetings',{headers:{Origin:'https://untrusted.example'}});
 assert.equal(denied.status,403,name+': untrusted origin accepted');
 const ui=await fetch(route+'/q/swagger-ui/');
 assert(ui.ok,name+': Swagger UI unavailable');
 assert((await ui.text()).includes('SwaggerUIBundle'),name+': missing Swagger UI HTML');
 const bundle=await fetch(route+'/q/swagger-ui/swagger-ui-bundle.js');
 assert(bundle.ok,name+': Swagger JavaScript unavailable');
 console.log(JSON.stringify({service:name,providedApi:entity.metadata.name,openapi:definition.openapi,swaggerUI:route+'/q/swagger-ui/',testerStatus:response.status}));
}
})().catch(e=>{console.error(e.message);process.exit(1)});
