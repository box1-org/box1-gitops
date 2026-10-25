# Provided API and tester verification

Verified on 2026-10-25. The template now emits both Component and OpenAPI API
entities, with `spec.providesApis` connecting them. It enables production Swagger
UI, configures the public HTTPS server, and permits CORS from the Hub origin.
The same changes are deployed to all three existing Quarkus services.

The committed `scripts/verify-service-apis.cjs` passed for each service:

```jsonl
{"service":"orders-service","providedApi":"orders-service-api","openapi":"3.1.0","swaggerUI":"https://orders-service-dev.apps.ocp.box1.org/q/swagger-ui/","testerStatus":200}
{"service":"quarkus-reference","providedApi":"quarkus-reference-api","openapi":"3.1.0","swaggerUI":"https://quarkus-reference.apps.ocp.box1.org/q/swagger-ui/","testerStatus":200}
{"service":"quarkus-golden-path-smoke","providedApi":"quarkus-golden-path-smoke-api","openapi":"3.1.0","swaggerUI":"https://quarkus-golden-path-smoke.apps.ocp.box1.org/q/swagger-ui/","testerStatus":200}
```

For each service, the verifier checked the processed `providesApi` catalog
relation, resolved live API definition, public server URL, greeting/info paths,
HTTP 200 tester request with the expected CORS response header, HTTP 403 from
an untrusted origin, Swagger HTML, and the Swagger JavaScript asset. No browser
was needed for these technical acceptance checks.

All three build TaskRuns completed successfully, including Maven verification
with the new CORS tests. Golden Path rendering passed for four service names.
Developer Hub and all three service Applications were Synced and Healthy, and
all three Deployment rollouts completed.

GitOps promotion PRs #14, #15, and #16 were merged with successful required
checks. The original orders-service release PipelineRun remains Failed because
its first GitOps validation Pod observed its temporary credential Secret before
creation. The required check was rerun successfully before PR #14 was merged.
The original reference release PipelineRun remains Failed after GitHub returned
HTTP 504 for its merge request; PR #15 did merge successfully. These historical
pipeline failures do not indicate failed application builds or rollouts.

API definitions are loaded from the deployed `/q/openapi` document. For future
template services, the API entity requires a successful first deployment before
the catalog can load its definition. Instructions are included in each generated
README and the platform README.
