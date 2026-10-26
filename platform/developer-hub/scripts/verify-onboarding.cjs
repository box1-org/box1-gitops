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
const name=process.env.SERVICE_NAME||'shipping-service';
const {Kube,Workflow}=require('/opt/app-root/src/dynamic-plugins-root/box1-scaffolder-onboarding-dynamic-1.1.0/workflow.cjs');
const kube=new Kube();
const cm=await kube.get('/api/v1/namespaces/rhdh/configmaps/box1-onboard-'+name);
assert(cm,'Missing onboarding state');const state=JSON.parse(cm.data['status.json']);
assert.equal(state.phase,'COMPLETE');
const run=await kube.get('/apis/tekton.dev/v1/namespaces/box1-ci/pipelineruns/'+state.pipelineName);
assert(run.status.conditions.some(c=>c.type==='Succeeded'&&c.status==='True'));
const ready=state.history.find(s=>s.phase==='PLATFORM_READY');
const buildRecorded=state.history.find(s=>s.phase==='BUILD_RUNNING');
assert(Date.parse(buildRecorded.at)>=Date.parse(ready.at),'CI was recorded before platform readiness');
// ObjectMeta creationTimestamp has whole-second precision; state timestamps retain milliseconds.
assert(Math.floor(Date.parse(run.metadata.creationTimestamp)/1000)>=Math.floor(Date.parse(ready.at)/1000),'CI creation predates platform readiness');
assert.equal(await kube.get('/api/v1/namespaces/box1-ci/secrets/'+state.credentialSecret),null,'Build credential not cleaned up');
const app=await kube.get('/apis/argoproj.io/v1alpha1/namespaces/openshift-gitops/applications/'+name);
assert.equal(app.status.sync.status,'Synced');assert.equal(app.status.health.status,'Healthy');
const deployment=await kube.get('/apis/apps/v1/namespaces/'+state.namespace+'/deployments/'+name);
assert.equal(deployment.spec.template.spec.containers[0].image,state.deploymentImage);
assert.equal(deployment.status.observedGeneration,deployment.metadata.generation);assert(deployment.status.availableReplicas>=1);
const entity=await api('/catalog/entities/by-name/component/default/'+name);
assert(entity.spec.providesApis.includes(name+'-api'));
const resources=await api('/kubernetes/services/'+name,{entity,auth:{}});
const cluster=resources.items.find(c=>c.cluster.name==='box1');assert.deepEqual(cluster.errors,[]);
const runs=cluster.resources.filter(r=>r.type==='customresources').flatMap(r=>r.resources).filter(r=>r.kind==='PipelineRun');
assert.equal(runs.length,1,'Onboarding created duplicate initial builds');
assert.equal(runs[0].metadata.name,state.pipelineName);
const {ConfigReader}=require('@backstage/config');
const {ScmIntegrations,DefaultGithubCredentialsProvider}=require('@backstage/integration');
const config=new ConfigReader({integrations:{github:[{host:'github.com',apps:[{appId:process.env.GITHUB_APP_ID,clientId:process.env.GITHUB_APP_CLIENT_ID,clientSecret:process.env.GITHUB_APP_CLIENT_SECRET,privateKey:process.env.GITHUB_APP_PRIVATE_KEY}]}]}});
const credentials=DefaultGithubCredentialsProvider.fromIntegrations(ScmIntegrations.fromConfig(config));
const w=new Workflow({ctx:{input:{name}},config,credentials});
const commits=await w.github('/repos/box1-org/'+name+'/commits?per_page=100');
assert.equal(commits[0].sha,state.sourceRevision,'An additional source commit was pushed');
assert.equal(commits.length,2,'Expected only marker initialization and initial generated source commits');
const prs=[];
for(const field of ['onboardingPR','promotionPR']){
 const match=/^https:\/\/github\.com\/box1-org\/(box1-gitops|box1-workloads-dev)\/pull\/(\d+)$/.exec(state[field].url);
 assert(match && Number(match[2])===state[field].number,'Unexpected recorded PR repository');
 const repo='/repos/box1-org/'+match[1];
 const pr=await w.github(repo+'/pulls/'+state[field].number);
 assert(pr.merged);assert.equal(pr.merged_by.type,'Bot','PR was manually merged');
 const matches=await w.github(repo+'/pulls?state=all&head='+encodeURIComponent('box1-org:'+pr.head.ref)+'&base=main');
 assert.equal(matches.length,1,'Duplicate PRs created');
 const checks=(await w.github(repo+'/commits/'+pr.head.sha+'/check-runs?per_page=100')).check_runs;
 const required=['Pipelines as Code CI / box1-phase1-smoke-','Pipelines as Code CI / box1-gitops-validate-'];
 const selected={};for(const check of checks.sort((a,b)=>a.id-b.id))if(required.includes(check.name)&&check.app.slug==='box1-pipelines')selected[check.name]=check;
 assert(required.every(n=>selected[n]?.conclusion==='success'),'Required GitOps checks did not pass');
 prs.push({url:pr.html_url,mergedBy:pr.merged_by.login,head:pr.head.sha,checks:required.map(n=>({name:n,conclusion:selected[n].conclusion}))});
}
const response=await fetch('https://'+state.namespace+'.apps.ocp.box1.org/api/info');assert(response.ok);const info=await response.json();assert.equal(info.name,name);assert.equal(info.gitRef,state.sourceRevision);
console.log(JSON.stringify({service:name,state:state.phase,sourceRevision:state.sourceRevision,sourceCommits:commits.length,pipeline:state.pipelineName,pipelineCreatedAt:run.metadata.creationTimestamp,platformReadyAt:ready.at,buildRecordedAt:buildRecorded.at,buildCount:runs.length,image:state.deploymentImage,argoSync:app.status.sync.status,argoHealth:app.status.health.status,publicEndpointStatus:response.status,info,prs,credentialSecretDeleted:true},null,2));
})().catch(error=>{console.error(error.message);process.exit(1)});
