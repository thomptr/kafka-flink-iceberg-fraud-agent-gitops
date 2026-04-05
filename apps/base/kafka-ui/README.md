# Kafbat UI (Kafka UI)

Web UI for the Strimzi Kafka cluster, installed from the [Kafbat Helm chart](https://ui.docs.kafbat.io/configuration/helm-charts/quick-start).

- **Bootstrap**: `platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092` (plain listener, same as other in-cluster clients).
- **Minikube**: the overlay sets **NodePort** on the Service; find the port with `kubectl -n kafka-ui get svc`.
- **Auth**: disabled in `yamlApplicationConfig` for local use; tighten for shared environments per [Kafbat configuration](https://ui.docs.kafbat.io/).
