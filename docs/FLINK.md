# Flink Operations

## Jobs

Two persistent streaming jobs run continuously in the `flink-system` namespace:

| Name | Purpose |
|------|---------|
| `fraud-score-enricher` | Reads transactions from Kafka, enriches with fraud scores, writes to Iceberg |
| `sample-fraud-stream` | Secondary streaming job |

Both jobs have `state: running` in their FlinkDeployment specs and should always be in `RUNNING` lifecycle state. If either shows `FAILED`, manual intervention is required.

## Checking Status

```bash
kubectl get flinkdeployment -n flink-system
```

Healthy output:

```
NAME                   JOB STATUS   LIFECYCLE STATE
fraud-score-enricher   RUNNING      RUNNING
sample-fraud-stream    RUNNING      RUNNING
```

## Restarting After a Failure (e.g. Post-Reboot)

### Symptoms

- `JOB STATUS` and `LIFECYCLE STATE` both show `FAILED`
- Job manager logs show `java.net.UnknownHostException: polaris.polaris.svc.cluster.local: Temporary failure in name resolution`

### Root Cause

On cluster reboot, Flink job managers start before CoreDNS is ready. Any catalog connection (e.g. to the Polaris REST catalog) that fires during job initialization will receive a DNS failure. Flink treats this as a terminal `FAILED` state and does not auto-recover.

### Fix

Patch `restartNonce` to force the Flink operator to redeploy both jobs:

```bash
kubectl patch flinkdeployment -n flink-system fraud-score-enricher \
  --type=merge -p '{"spec":{"restartNonce":1}}'

kubectl patch flinkdeployment -n flink-system sample-fraud-stream \
  --type=merge -p '{"spec":{"restartNonce":1}}'
```

If you restart again later, increment the nonce value (e.g. `2`, `3`, ...) — the value just needs to change from whatever is currently set.

### Verify Recovery

```bash
kubectl get flinkdeployment -n flink-system --watch
```

Wait until both show `RUNNING / RUNNING`. Takes ~60–90 seconds.

Check job manager logs if it doesn't come up:

```bash
kubectl logs -n flink-system -l app=fraud-score-enricher --tail=50
kubectl logs -n flink-system -l app=sample-fraud-stream --tail=50
```

## Prerequisites Before Restarting Flink

Flink depends on Kafka and Polaris. Confirm both are healthy before restarting Flink jobs, otherwise the jobs will fail again immediately.

```bash
# Kafka broker
kubectl get pod -n kafka -l strimzi.io/name=platform-cluster-kafka

# Polaris catalog
kubectl get pod -n polaris -l app=polaris
```

Both should show `Running` with all containers ready.
