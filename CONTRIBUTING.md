# Contributing

## Workflow

1. Make changes through a pull request.
2. Keep platform changes, workload changes, and documentation changes explicit.
3. Run `make validate` before requesting review.
4. Do not commit plaintext credentials or kubeconfig material.
5. Update the relevant README or runbook when bootstrap, ownership, or rollback behavior changes.

## Review Expectations

- Shared infrastructure changes require platform-owner review.
- Workload changes must declare dependencies on shared services.
- Every change must include validation evidence and a rollback note.
