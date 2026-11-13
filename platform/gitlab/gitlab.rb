# Omnibus configuration (GITLAB_OMNIBUS_CONFIG). Target: about 4 GiB in total,
# following GitLab's "memory-constrained environments" guidance.
external_url 'https://gitlab.apps.ocp.box1.org'
nginx['listen_port'] = 8929
nginx['listen_https'] = false
nginx['proxy_set_headers'] = { 'X-Forwarded-Proto' => 'https', 'X-Forwarded-Ssl' => 'on' }
letsencrypt['enable'] = false
package['modify_kernel_parameters'] = false

# Memory
puma['worker_processes'] = 0
puma['min_threads'] = 1
puma['max_threads'] = 4
sidekiq['concurrency'] = 5
postgresql['shared_buffers'] = '128MB'
postgresql['max_worker_processes'] = 4
gitlab_rails['env'] = { 'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000' }
gitaly['env'] = { 'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000', 'GITALY_COMMAND_SPAWN_MAX_PARALLEL' => '2' }
gitaly['configuration'] = {
  concurrency: [
    { 'rpc' => '/gitaly.SmartHTTPService/PostReceivePack', 'max_per_repo' => 3 },
    { 'rpc' => '/gitaly.SSHService/SSHUploadPack', 'max_per_repo' => 3 },
  ],
}

# Off: not needed for the proof
prometheus_monitoring['enable'] = false
gitlab_exporter['enable'] = false
registry['enable'] = false
gitlab_rails['registry_enabled'] = false
gitlab_pages['enable'] = false
gitlab_kas['enable'] = false
mattermost['enable'] = false
gitlab_rails['usage_ping_enabled'] = false
gitlab_rails['packages_enabled'] = false
gitlab_rails['dependency_proxy_enabled'] = false
gitlab_rails['incoming_email_enabled'] = false
gitlab_rails['gitlab_email_enabled'] = false

gitlab_rails['monitoring_whitelist'] = ['127.0.0.0/8']
