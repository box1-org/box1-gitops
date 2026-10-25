// Execute inside backstage-backend: kubectl exec -i ... -- node < this-file
// Uses the existing automation backend credential without emitting it.
const assert = require('node:assert/strict');
const base = 'http://localhost:7007/api';
async function api(path, body) {
  const response = await fetch(base + path, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${process.env.BACKEND_SECRET}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  assert(response.ok, `${path}: HTTP ${response.status}: ${await response.clone().text()}`);
  return response.json();
}
(async () => {
  for (const name of ['quarkus-reference', 'orders-service']) {
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
    assert(pods?.resources.length, 'No Pods resolved');
    const custom = resources.filter(r => r.type === 'customresources').flatMap(r => r.resources);
    assert(custom.some(r => r.kind === 'Route' && r.metadata.name === name), 'Route not resolved');
    const runs = custom.filter(r => r.kind === 'PipelineRun' && r.metadata.namespace === 'box1-ci');
    assert(runs.length, 'CI runs not resolved');
    const selector = encodeURIComponent(entity.metadata.annotations['argocd/app-selector']);
    const argo = await api(`/argocd/argoInstance/openshift-gitops/applications/selector/${selector}`);
    assert(argo.items?.some(a => a.metadata.name === name), 'Argo CD Application not resolved');
    console.log(JSON.stringify({ entity: name, cluster: cluster.cluster.name,
      deployments: deployment.resources.length, pods: pods.resources.length, pipelineRuns: runs.length,
      argoApplications: argo.items.map(a => ({ name: a.metadata.name, sync: a.status.sync.status, health: a.status.health.status })) }));
  }
})().catch(error => { console.error(error.message); process.exit(1); });
