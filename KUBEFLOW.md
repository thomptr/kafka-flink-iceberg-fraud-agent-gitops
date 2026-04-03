
# Connecting to the dashboard through Istio

```sh
kubectl --context=fraud-gitops -n istio-system port-forward svc/istio-ingressgateway 8080:80
```

Default credentials : user@example.com/12341234
