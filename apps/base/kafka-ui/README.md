# Kafbat UI (Kafka UI)

Web UI for the Strimzi Kafka cluster, installed from the [Kafbat Helm chart](https://ui.docs.kafbat.io/configuration/helm-charts/quick-start).

The `kafka-ui` namespace is defined here (`namespace.yaml`) so the **apps** bundle creates it before the `HelmRelease` (same as `infra-configs` `platform-namespaces`, if that has already reconciled). If you see `namespace "kafka-ui" not found`, apply or reconcile **apps** once, or run `kubectl create namespace kafka-ui`.

- **Bootstrap**: `platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092` (plain listener, same as other in-cluster clients).
- **Minikube**: the overlay sets **NodePort** on the Service; find the port with `kubectl -n kafka-ui get svc`.
- **Auth**: disabled in `yamlApplicationConfig` for local use; tighten for shared environments per [Kafbat configuration](https://ui.docs.kafbat.io/).

## If `helmrelease kafka-ui` is NotFound

The object is only created after the **`apps`** Flux `Kustomization` (path `./apps/minikube`) reconciles **from Git** with these files included. Typical causes: changes not **pushed**, Flux tracking another **branch**, or **`apps`** stuck / failing.

Check:

```bash
kubectl config current-context
flux get kustomizations
kubectl -n flux-system get kustomization apps -o jsonpath='{.status.conditions[?(@.type=="Ready")]}' ; echo
kubectl get helmrelease -A
```

Force a sync (needs `flux` CLI):

```bash
flux reconcile source git flux-system
flux reconcile kustomization apps --with-source
```

Apply the bundle manually from a clone that contains `apps/base/kafka-ui` (same as Flux):

```bash
cd /path/to/kafka-flink-iceberg-fraud-agent-gitops
kubectl apply -k apps/minikube
kubectl -n kafka-ui get helmrelease,svc
```
