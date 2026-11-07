# MailHog

In-cluster SMTP sink for `notification-service` operator notices
([box1-docs#16](https://github.com/box1-org/box1-docs/issues/16)). Notices are real SMTP messages that stay
inside the cluster; MailHog is the final sink and never relays mail onward.

| What | Value |
| --- | --- |
| SMTP (cluster-internal) | `mailhog.mailhog.svc.cluster.local:1025`, no auth, no TLS |
| Web UI and API | <https://mailhog.apps.ocp.box1.org> (OpenShift login) |
| Storage | Maildir on the `mailhog-maildir` PVC (1 GiB), survives pod restarts |
| Image | `docker.io/mailhog/mailhog` v1.0.1 by digest, amd64 |

## Access

- **SMTP:** the NetworkPolicy admits port 1025 only from `notification-service-dev`.
- **Web UI and API:** MailHog listens on loopback; the `ose-oauth-proxy` sidecar is the only way in. A user
  needs `get` on the `mailhog-web` Service in this namespace (cluster admins have it). Grant others with
  `oc adm policy add-role-to-user view <user> -n mailhog`.
- **Scripts:** a bearer token with the same permission reaches the API through the Route, for example:

  ```bash
  curl -sS -H "Authorization: Bearer $(oc whoami -t)" https://mailhog.apps.ocp.box1.org/api/v2/messages?limit=5
  ```

## Mailboxes

| Notice | Recipient |
| --- | --- |
| `ORDER_SHIPPED`, `SHIPMENT_DELAYED`, `SHIPMENT_FAILED` | `ops-fulfillment@box1.local` |
| `ORDER_EXCEPTION`, `ORDER_REJECTED` | `ops-orders@box1.local` |

Sender: `box1-notifications@box1.local`. Messages carry only internal operational identifiers.

## Operations

- **Clear the mailbox:** `DELETE /api/v1/messages` through the Route, or the UI's *Delete all messages*.
- **Recovery:** deleting the Deployment's pod keeps the mailbox (Maildir on the PVC). Deleting the PVC empties it.
- **Removal:** delete `applications/mailhog.yaml`; Argo CD prunes the namespace contents. Set
  `NOTIFY_PROVIDER=stub` on notification-service first, or its deliveries retry and fail.
