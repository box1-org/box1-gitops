# Hawtio Online

This directory installs the Red Hat build of HawtIO operator and a cluster-mode
`Hawtio` console through separate Argo CD Applications, following the Dev Spaces
pattern.

- `operator/`: `hawtio` namespace, an AllNamespaces `OperatorGroup`, and a
  `red-hat-hawtio-operator` Subscription (channel `v2`, catalog
  `redhat-operators-v422`) with `installPlanApproval: Manual`.
- `instance/`: the `hawtio-online` `Hawtio` CR (`type: Cluster`) and the Role
  that lets the Argo CD application controller manage it.

Both Applications are manual-sync. Sync `hawtio-operator`, approve its
InstallPlan, wait for the CSV to succeed, then sync `hawtio`.

## Access

On OpenShift the console authenticates with OpenShift OAuth; users see only the
pods in projects they can access. The operator adds a console link to the
OpenShift application menu.

## Connecting applications

Hawtio discovers pods that expose a container port named `jolokia`. It connects
to the Jolokia agent over HTTPS using a client certificate signed by the
cluster service CA, with CN `hawtio-online.hawtio.svc`. Agents must:

- serve Jolokia over HTTPS on the `jolokia` port;
- require client certificates signed by the service CA
  (`/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`);
- accept `clientPrincipal` `cn=hawtio-online.hawtio.svc`.

The `fulfillment-adapter` workload is the first application configured this way.
