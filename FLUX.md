# FluxCD commands 

Get Kustomizations status
```sh
flux --context=fraud-gitops get kustomizations -A
```

Force reconciliation
```sh
flux --context=fraud-gitops reconcile kustomization apps -n flux-system --with-source
```