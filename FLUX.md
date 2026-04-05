# FluxCD commands

## Set the context

```sh
kubectl config use-context fraud-gitops
```

If you use another context name, omit `--context=fraud-gitops` or substitute your current context.

## Where changes land

| Area | Kustomization | Path in repo |
|------|---------------|--------------|
| Grafana / kube-prometheus-stack / Strimzi operators | `infra-controllers` | `./infrastructure/controllers/minikube` |
| Kafka (Strimzi CRs, metrics, etc.) | `infra-configs` | `./infrastructure/configs/minikube` |
| Application workloads | `apps` | `./apps/minikube` |

**Dependency order:** `infra-controllers` → `infra-configs` → `apps`. If `infra-controllers` is not **Ready**, Flux will not successfully reconcile the later Kustomizations.

## Git source (must match the cluster)

The `GitRepository` **flux-system** tracks **`main`** on the remote in `gotk-sync` (or bootstrap). **Flux only applies what is pushed to that branch.** Local commits that are not pushed, or work on another branch, will not show up after reconcile.

## Bootstrap Flux

Bootstrap this repo to the cluster entrypoint at `clusters/minikube`:

```sh
flux bootstrap github \
  --owner <github-user-or-org> \
  --repository <repo-name> \
  --branch main \
  --path clusters/minikube
```

If your current kube context is not `fraud-gitops`, switch it first or add `--context=<your-context>` to the `flux` commands.

## Status

```sh
flux --context=fraud-gitops get all -A
flux --context=fraud-gitops get sources git -A
flux --context=fraud-gitops get kustomizations -A
```

Inspect failures:

```sh
kubectl --context=fraud-gitops describe gitrepository flux-system -n flux-system
kubectl --context=fraud-gitops describe kustomization infra-controllers -n flux-system
kubectl --context=fraud-gitops describe kustomization infra-configs -n flux-system
kubectl --context=fraud-gitops describe kustomization apps -n flux-system
```

## Force reconciliation (full chain)

Reconcile **source** first, then **root** `flux-system` (applies `clusters/minikube`, including the child Kustomization CRs), then **children** in order:

```sh
flux --context=fraud-gitops reconcile source git flux-system -n flux-system
flux --context=fraud-gitops reconcile kustomization flux-system -n flux-system --with-source

flux --context=fraud-gitops reconcile kustomization infra-controllers -n flux-system --with-source
flux --context=fraud-gitops reconcile kustomization infra-configs -n flux-system --with-source
flux --context=fraud-gitops reconcile kustomization apps -n flux-system --with-source
```

**Note:** Reconciling only `apps` does **not** refresh Kafka or Grafana manifests; use `infra-configs` and `infra-controllers` as above.

## When reconcile “does nothing”

1. **Wrong branch / not pushed** — Confirm `git push origin main` and that your changes are on `main`.
2. **Git auth** — `GitRepository` status should show the latest **revision** matching GitHub. If auth fails, fix the `flux-system` secret (deploy key) or URL in the `GitRepository`.
3. **Upstream Kustomization failing** — Read `Status.conditions` / events on `infra-controllers` (Helm timeouts, CRD ordering, etc.); fix that before expecting `infra-configs` or `apps` to go Ready.
4. **Suspended** — `flux get kustomizations` shows **Suspended=true**; resume with `flux resume kustomization <name> -n flux-system`.
5. **Wrong kubectl context** — `kubectl config current-context` must be the cluster where Flux runs (`fraud-gitops` in this doc).
