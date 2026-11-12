import k8s

inputs = k8s.inputs()
app = k8s.require(inputs, ["PAC_GITHUB_APP_ID", "PAC_GITHUB_APP_PRIVATE_KEY", "PAC_WEBHOOK_SECRET"],
                  "pipelines-as-code-secret (GitHub App for Pipelines as Code)")
if app:
    k8s.apply_secret(k8s.NAMESPACE, "pipelines-as-code-secret", {
        "github-application-id": app["PAC_GITHUB_APP_ID"].strip(),
        "github-private-key": app["PAC_GITHUB_APP_PRIVATE_KEY"],
        "webhook.secret": app["PAC_WEBHOOK_SECRET"].strip(),
    })
k8s.finish()
