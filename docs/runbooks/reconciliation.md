# Reconciliation and Rollback Runbook

## Health Checks

```bash
flux get sources git -A
flux get kustomizations -A
kubectl get helmreleases -A
```

## Expected Signals

- `infra-controllers` is ready before `infra-configs`
- `infra-configs` is ready before `apps`
- Monitoring dashboards and operator pods report healthy status

## Rollback

1. Revert the offending Git change.
2. Merge the revert through the normal review flow.
3. Re-run `make validate`.
4. Wait for Flux to reconcile the prior approved state.

## Evidence for Reviewers

- Managed paths changed
- Validation output
- Any secret handling changes
- Rollback plan
