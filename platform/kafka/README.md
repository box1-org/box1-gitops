# Box1 Kafka

This directory declares the shared single-node Kafka event stream used by
services that opt into Kafka in the Create Quarkus Service template.

The Kafka, KafkaNodePool, and service-created KafkaTopic manifests use the
served `kafka.strimzi.io/v1` API. The installed operator may retain `v1beta2`
as its storage version, but new manifests should use `v1`.

The `kafka-operator` Application installs the Red Hat AMQ Streams Operator in
the existing `openshift-operators` namespace with manual InstallPlan approval.
The `box1-kafka` Application then creates a one-node KRaft broker in the
`box1-kafka` namespace, backed by a 10 GiB persistent claim. The internal
bootstrap service is `box1-kafka-kafka-bootstrap.box1-kafka.svc:9092`.

Service-created `KafkaTopic` resources are watched across namespaces by the
Topic Operator and use the `box1-kafka` cluster label. This is a lab profile:
one broker, one controller, replication factor one, and no node-level HA.

Before synchronization, review the AMQ Streams channel and supported Kafka
CRD version on the target cluster. Approve the Operator InstallPlan manually,
wait for its CSV and CRDs to become ready, then synchronize `box1-kafka`.
No cluster mutation is performed by this repository change.
