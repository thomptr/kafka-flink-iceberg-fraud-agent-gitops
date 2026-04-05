# Kubeflow on Minikube

Training workloads typically need a **GPU**. On Minikube, use **`--gpus all`** once the host passes GPUs into Docker (see **GPU** under Minikube in `docs/runbooks/bootstrap.md`). Until that works, use a CPU-only profile for the rest of the platform.

# Connecting to the dashboard through Istio

```sh
kubectl --context=fraud-gitops -n istio-system port-forward svc/istio-ingressgateway 8085:80
```

Default credentials : user@example.com/12341234
