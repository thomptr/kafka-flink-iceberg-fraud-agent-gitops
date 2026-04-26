# Flink job recovery runbook

Covers the two most common failure patterns for the Flink jobs in this cluster.

---

## Scenario 1 — All Flink jobs FAILED after Polaris (Iceberg catalog) restart

### Symptoms

```
kubectl get flinkdeployments -n flink-system
NAME                          LIFECYCLE STATE   JOB STATUS   AVAILABLE
fraud-score-enricher          FAILED            FAILED
fraud-score-kafka-publisher   FAILED            FAILED
sample-fraud-stream           FAILED            FAILED
```

All three jobs fail simultaneously. Pod logs show DNS resolution errors for Polaris:

```
Caused by: java.net.UnknownHostException: polaris.polaris.svc.cluster.local
```

or connection-refused errors against port 8181. The Polaris pod itself is healthy by the time you investigate.

### Root cause

The Flink Kubernetes Operator marks a `FlinkDeployment` as `FAILED` after consecutive restart attempts exceed its retry budget. When Polaris restarts, in-flight catalog calls fail, which crashes all three jobs within seconds of each other. Flink's retry budget exhausts before Polaris finishes restarting, so the jobs stay `FAILED` even after Polaris is healthy.

### Fix

Trigger a stateless restart for each job by bumping `spec.job.restartNonce` in the `FlinkDeployment`. The Flink operator detects the change and performs a clean restart using the current upgrade mode.

**Important**: `fraud-score-enricher` uses `upgradeMode: stateless` (changed from `last-state` after this incident — see commit history). `sample-fraud-stream` uses `upgradeMode: last-state` and will restore from the latest checkpoint.

```bash
# Re-trigger all three jobs
kubectl patch flinkdeployment -n flink-system sample-fraud-stream \
  --type merge -p '{"spec":{"job":{"restartNonce":1}}}'

kubectl patch flinkdeployment -n flink-system fraud-score-enricher \
  --type merge -p '{"spec":{"job":{"restartNonce":1}}}'

kubectl patch flinkdeployment -n flink-system fraud-score-kafka-publisher \
  --type merge -p '{"spec":{"job":{"restartNonce":1}}}'
```

Increment the nonce value each time you use this (1, 2, 3, …). FluxCD will reconcile the manifest back to the committed value within one sync interval (~10 min), but by then the jobs are running and FluxCD will find nothing to change.

Verify recovery:

```bash
kubectl get flinkdeployments -n flink-system -w
```

All three should reach `RUNNING / STABLE` within 2–3 minutes.

### Why `upgradeMode: last-state` was changed to `stateless` for `fraud-score-enricher`

`last-state` requires a valid checkpoint to restore from. After Polaris-induced failures, the checkpoint may be corrupt or absent, causing the job to loop in `RESTARTING` indefinitely. `stateless` lets the job start fresh without checkpoint dependency, which is acceptable for the enricher since it reads the Iceberg table from the beginning on restart (the table is the source of truth).

---

## Scenario 2 — `fraud-score-kafka-publisher` spawns 19+ taskmanager pods

### Symptoms

```
kubectl get pods -n flink-system | grep kafka-publisher-taskmanager
fraud-score-kafka-publisher-taskmanager-1-1    0/1  Pending  ...
fraud-score-kafka-publisher-taskmanager-1-2    0/1  Pending  ...
...  (up to 19 pods)
```

The Flink UI shows the `TableSourceScan` operator with `parallelism=38` despite the job being configured with `parallelism=1`.

JM logs:

```
need request 8 new workers, current worker number 11, declared worker number 19
Creating new TaskManager pod with name fraud-score-kafka-publisher-taskmanager-1-20
```

### Root cause

Iceberg Flink connector 1.9.2 introduces `FlinkConfigOptions.TABLE_EXEC_ICEBERG_INFER_SOURCE_PARALLELISM` which defaults to `true`. When enabled, the Iceberg `IcebergTableSource` sets the source operator's parallelism to the number of discovered data file splits rather than the configured job parallelism. The `transactions_scored` table had ~38 Parquet files, resulting in 38 source subtasks → 19 TaskManagers (2 slots each).

The following **do not** fix this because they target a non-existent option:

- `SET 'parallelism.default' = '1'` — `SqlRunner.executeSql()` does not support `SET` statements
- `ALTER TABLE ... SET ('read.parallelism' = '1')` — `read.parallelism` is absent from `FlinkReadOptions` in Iceberg 1.9.2
- `/*+ OPTIONS('read.parallelism'='1') */` SQL hint — same; option does not exist

### Fix

Add `table.exec.iceberg.infer-source-parallelism: "false"` to the `flinkConfiguration` block of the `fraud-score-kafka-publisher` `FlinkDeployment`. This tells the Iceberg connector to use `table.exec.resource.default-parallelism` (already set to `"1"`) rather than inferring from split count.

This is committed in `apps/base/flink-jobs/resources.yaml`. If you see this regression after a rollback, re-apply:

```yaml
# apps/base/flink-jobs/resources.yaml — fraud-score-kafka-publisher flinkConfiguration
table.exec.resource.default-parallelism: "1"
table.exec.iceberg.infer-source-parallelism: "false"
```

After FluxCD reconciles (or after a manual `kubectl apply`), the operator performs a stateless restart. The job graph is recompiled with the new configuration and the source operator gets `parallelism=1`. Excess TM pods are terminated automatically.

Verify:

```bash
JM=$(kubectl get pod -n flink-system -l component=jobmanager,app=fraud-score-kafka-publisher -o jsonpath='{.items[0].metadata.name}')
JOB_ID=$(kubectl exec -n flink-system $JM -- curl -s http://localhost:8081/jobs | python3 -c "import json,sys; print(json.load(sys.stdin)['jobs'][0]['id'])")
kubectl exec -n flink-system $JM -- curl -s http://localhost:8081/jobs/$JOB_ID/plan \
  | python3 -c "import json,sys; [print(f'parallelism={n[\"parallelism\"]} {n[\"description\"][:60]}') for n in json.load(sys.stdin)['plan']['nodes']]"
```

Expected: all operators show `parallelism=1`.

---

## Scenario 3 — No jobs running in the Flink UI

### Symptoms

The Flink UI (reachable via the ingress on port 8085) shows no running jobs, or jobs are listed as `FAILED` / `CANCELED`. The `FlinkDeployment` resources confirm the state:

```bash
kubectl --context=fraud-gitops get flinkdeployments -n flink-system
NAME                          JOB STATUS   LIFECYCLE STATE
fraud-score-enricher          FAILED       FAILED
fraud-score-kafka-publisher   FAILED       FAILED
sample-fraud-stream           FAILED       FAILED
```

### Step 1 — Open the Flink UI

```bash
kubectl --context=fraud-gitops -n istio-system port-forward svc/istio-ingressgateway 8085:80
```

Navigate to `http://localhost:8085/flink/`. If the UI is blank or all jobs show `FAILED`, proceed to Step 2.

### Step 2 — Identify the root cause

Check recent jobmanager logs for each failed job:

```bash
for job in fraud-score-enricher fraud-score-kafka-publisher sample-fraud-stream; do
  echo "=== $job ==="
  POD=$(kubectl --context=fraud-gitops get pod -n flink-system -l app=$job -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  [ -n "$POD" ] && kubectl --context=fraud-gitops logs -n flink-system $POD --tail=30 2>&1 | grep -E "Caused by|FAILED|Exception" | tail -5
done
```

Common causes and which scenario to follow:

| Log pattern | Scenario |
|---|---|
| `UnknownHostException: polaris.polaris.svc.cluster.local` | Scenario 1 (Polaris restart) |
| `KafkaError.*_TRANSPORT.*Broker transport failure` | Kafka restart — wait for Kafka to stabilise, then follow Scenario 1 steps |
| `19+ taskmanager pods` / source parallelism=38 | Scenario 2 |

### Step 3 — Restart the jobs

Check current nonce values to know what to increment to:

```bash
kubectl --context=fraud-gitops get flinkdeployments -n flink-system \
  -o jsonpath='{range .items[*]}{.metadata.name}{" nonce="}{.spec.job.restartNonce}{"\n"}{end}'
```

Bump each nonce by 1 (if currently unset, use `1`; if currently `1`, use `2`, etc.):

```bash
NONCE=1   # increment from current value

kubectl --context=fraud-gitops patch flinkdeployment -n flink-system sample-fraud-stream \
  --type merge -p "{\"spec\":{\"job\":{\"restartNonce\":$NONCE}}}"

kubectl --context=fraud-gitops patch flinkdeployment -n flink-system fraud-score-enricher \
  --type merge -p "{\"spec\":{\"job\":{\"restartNonce\":$NONCE}}}"

kubectl --context=fraud-gitops patch flinkdeployment -n flink-system fraud-score-kafka-publisher \
  --type merge -p "{\"spec\":{\"job\":{\"restartNonce\":$NONCE}}}"
```

### Step 4 — Verify recovery

```bash
kubectl --context=fraud-gitops get flinkdeployments -n flink-system -w
```

All three should reach `RUNNING / STABLE` within 2–3 minutes. Refresh the Flink UI — jobs should appear in the **Running Jobs** tab.

If a job stays in `RESTARTING` for more than 5 minutes, check the jobmanager pod logs for a new error and re-evaluate the root cause.

---

## FluxCD caveats

Both scenarios involve `kubectl patch` or `kubectl apply` commands that FluxCD will eventually reconcile back to the Git state. This is intentional — the Git state should always be the desired state.

If FluxCD is reconciling against a deleted or stale branch, manual patches will be reverted within the sync interval (~10 min). Check the active branch:

```bash
kubectl get gitrepository -n flux-system flux-system -o jsonpath='{.spec.ref.branch}'
```

If it shows an old branch, see `docs/runbooks/reconciliation.md` for how to update the watched branch.
