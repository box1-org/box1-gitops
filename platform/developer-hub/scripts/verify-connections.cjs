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
(async () => {
  for (const action of ['get', 'sync', 'delete']) {
    const response = await fetch('https://openshift-gitops-server-openshift-gitops.apps.ocp.box1.org/api/v1/account/can-i/applications/' + action + '/default%2Fquarkus-reference', {
      headers: { Authorization: `Bearer ${process.env.ARGOCD_AUTH_TOKEN}` },
    });
    assert(response.ok, 'Argo CD permission check failed');
    assert.equal((await response.json()).value, action === 'get' ? 'yes' : 'no');
  }
  for (const name of ['quarkus-reference']) {
    const entity = await api(`/catalog/entities/by-name/component/default/${name}`);
    assert.equal(entity.metadata.annotations['backstage.io/kubernetes-id'], name);
    assert(!entity.metadata.annotations['backstage.io/kubernetes-namespace'], 'Namespace restriction hides shared CI');
    const kubernetes = await api('/kubernetes/services/' + name, { entity, auth: {} });
    assert(kubernetes.items?.length, 'No clusters returned');
    const cluster = kubernetes.items.find(i => i.cluster.name === 'box1');
    assert(cluster, 'box1 not returned');
    assert.deepEqual(cluster.errors, [], 'Kubernetes backend returned errors');
    const resources = cluster.resources;
    const deployment = resources.find(r => r.type === 'deployments');
    assert(deployment?.resources.some(r => r.metadata.name === name), 'Workload not resolved');
    const pods = resources.find(r => r.type === 'pods');
    assert(pods?.resources.some(r => r.metadata.namespace === deployment.resources[0].metadata.namespace), 'No workload Pods resolved');
    const custom = resources.filter(r => r.type === 'customresources').flatMap(r => r.resources);
    assert(custom.some(r => r.kind === 'Route' && r.metadata.name === name), 'Route not resolved');
    const runs = custom.filter(r => r.kind === 'PipelineRun' && r.metadata.namespace === 'box1-ci');
    assert(runs.length, 'CI runs not resolved');
    const taskRuns = custom.filter(r => r.kind === 'TaskRun' && r.metadata.namespace === 'box1-ci');
    assert(taskRuns.length, 'CI TaskRuns not resolved');
    const selector = encodeURIComponent(entity.metadata.annotations['argocd/app-selector']);
    const argo = await api(`/argocd/argoInstance/openshift-gitops/applications/selector/${selector}`);
    assert(argo.items?.some(a => a.metadata.name === name), 'Argo CD Application not resolved');
    console.log(JSON.stringify({ entity: name, cluster: cluster.cluster.name,
      deployments: deployment.resources.length, pods: pods.resources.length, pipelineRuns: runs.length, taskRuns: taskRuns.length,
      argoApplications: argo.items.map(a => ({ name: a.metadata.name, sync: a.status.sync.status, health: a.status.health.status })) }));
  }
})().catch(error => { console.error(error.message); process.exit(1); });
