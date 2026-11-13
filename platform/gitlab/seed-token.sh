#!/bin/bash
# Runs in the GitLab container next to /assets/init-container. Waits for
# GitLab, then makes sure root has a personal access token equal to the
# gitlab-admin Secret's token. One gitlab-rails runner call, only when needed.
set -u
until curl -fsS http://127.0.0.1:8929/-/readiness >/dev/null 2>&1; do sleep 10; done
code=$(curl -s -o /dev/null -w '%{http_code}' -H "PRIVATE-TOKEN: ${BOX1_ROOT_TOKEN}" http://127.0.0.1:8929/api/v4/personal_access_tokens/self)
if [ "$code" = 200 ]; then echo "[seed-token] root token valid"; exit 0; fi
echo "[seed-token] seeding root token"
gitlab-rails runner '
u = User.find_by_username("root")
u.personal_access_tokens.where(name: "box1-bootstrap").each { |t| t.revoke! unless t.revoked? }
t = u.personal_access_tokens.build(name: "box1-bootstrap", scopes: %w[api], expires_at: 364.days.from_now)
t.set_token(ENV.fetch("BOX1_ROOT_TOKEN"))
t.save!
puts "[seed-token] done"
'
