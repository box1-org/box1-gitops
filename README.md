# box1-gitops

App of apps for gitops 

Applications:
- Red Hat Developer Hub

Developer Hub manifests and the staged Operator/instance rollout are documented in
[platform/developer-hub/README.md](platform/developer-hub/README.md).
Both child applications require manual sync; the root can register them without
installing the Operator or creating a Backstage instance.
