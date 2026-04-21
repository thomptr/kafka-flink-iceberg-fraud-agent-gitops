# Tasks: Flink Async I/O Model Scoring — Real-Time KServe Enrichment

**Input**: Design documents from `specs/003-mlops-lakehouse/`  
**Branch**: `003-mlops-lakehouse`  
**Spec**: [spec.md](./spec.md)

**Scope**: Extend the existing `jobs/flink-sql-runner/` Java project with two new classes — `KServeAsyncFunction` (Flink `RichAsyncFunction<Row, Row>` using the JDK 17 built-in `java.net.http.HttpClient`) and `ModelScorerJob` (DataStream + Table API hybrid job) — plus a new `fraud-score-enricher` FlinkDeployment that reads the existing `transactions` Iceberg table in streaming mode, calls KServe asynchronously, and writes enriched records to a new `transactions_scored` Iceberg table with a `fraud_probability DOUBLE` column.

**Existing state**:
- `jobs/flink-sql-runner/src/main/java/org/example/fraud/flink/SqlRunner.java` — working SQL runner; use `SqlRunner.applyPolarisCatalogConfigFromEnv()` and `SqlRunner.resolvePolarisOAuthCredential()` in the new job
- Flink 1.20.3, Java 17, Iceberg 1.9.2, no HTTP client dependency yet (JDK `java.net.http` is available built-in at Java 11+)
- Kafka connector, Iceberg Flink runtime, Hadoop AWS, and iceberg-aws-bundle are already in `pom.xml`
- `apps/base/flink-jobs/resources.yaml` has one `FlinkDeployment` (`sample-fraud-stream`); a second will be added
- Polaris catalog accessible at `http://polaris.polaris.svc.cluster.local:8181/api/catalog`, warehouse `quickstart_catalog`
- KServe InferenceService endpoint (in-cluster): `http://fraud-detector.kubeflow-user-example-com.svc.cluster.local/v2/models/fraud-detector/infer`

**Architecture decision**: Use the Flink Async I/O API (`AsyncDataStream.unorderedWait`) with JDK `HttpClient.sendAsync()`. No new Maven dependency required. The `transactions` Iceberg table is read in incremental streaming mode (`OPTIONS('streaming'='true', 'monitor-interval'='5s')`). Up to 100 concurrent KServe requests in flight per task manager slot. Errors and timeouts emit `fraud_probability = -1.0` (sentinel) so the Iceberg sink never stalls.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no in-progress dependencies)
- **[Story]**: US3 = Deploy Registered Model for Inference (Flink enrichment path)

---

## Phase 1: Setup

**Purpose**: Verify the `java.net.http` module is accessible in the project and the `flink-streaming-java` Async I/O classes are on the classpath; confirm the Iceberg streaming read hint syntax.

- [x] T001 Verify `flink-streaming-java` includes Async I/O: `grep -r "AsyncDataStream" ~/.m2/repository/org/apache/flink/flink-streaming-java/${flink.version}/` — confirm the class is present (it is always included in `flink-streaming-java`; this check confirms the Maven cache is populated); if absent, run `mvn dependency:resolve -f jobs/flink-sql-runner/pom.xml` first

- [x] T002 [P] Confirm Iceberg streaming option syntax: open `https://iceberg.apache.org/docs/latest/flink-queries/#streaming-reads` (reference only — do not commit) and note the correct SQL hint syntax for Flink 1.20: `/*+ OPTIONS('streaming'='true', 'monitor-interval'='5s') */`; record in a code comment in `ModelScorerJob.java` (T007)

---

## Phase 2: Foundational

**Purpose**: Create the `transactions_scored` Iceberg table DDL so it exists before the streaming job starts writing.

- [x] T003 Create `apps/base/flink-jobs/flink_scored_ddl.sql` — a one-shot SQL script that creates the output table if it does not exist:
  ```sql
  -- Polaris REST catalog. Credential overridden at runtime by SqlRunner.
  CREATE CATALOG polaris_catalog WITH (
    'type' = 'iceberg',
    'catalog-type' = 'rest',
    'uri' = 'http://polaris.polaris.svc.cluster.local:8181/api/catalog',
    'warehouse' = 'quickstart_catalog',
    'credential' = 'root:changeme',
    'scope' = 'PRINCIPAL_ROLE:ALL'
  );

  CREATE DATABASE IF NOT EXISTS `polaris_catalog`.`default`;

  CREATE TABLE IF NOT EXISTS `polaris_catalog`.`default`.`transactions_scored` (
    transaction_id     STRING,
    user_id            INT,
    amount             DOUBLE,
    merchant           STRING,
    lat                DOUBLE,
    lon                DOUBLE,
    ts                 TIMESTAMP(3),
    processing_time    TIMESTAMP(3),
    amount_velocity_5min   DOUBLE,
    distance_from_home_km  DOUBLE,
    fraud_probability  DOUBLE
  ) WITH (
    'format-version' = '2',
    'write.distribution-mode' = 'hash'
  );
  ```

- [x] T004 Add a Kubernetes `Job` resource to `apps/base/flink-jobs/resources.yaml` named `create-transactions-scored-table` that runs the existing `flink-sql-runner` image once with args `["/opt/flink/sql/flink_scored_ddl.sql"]`; mount the new SQL as a `ConfigMap` volume; set `restartPolicy: OnFailure`; annotate with `"helm.sh/hook": "pre-install,pre-upgrade"` so it runs before the FlinkDeployment

- [x] T005 Add `flink-scored-ddl` ConfigMap entry to `apps/base/flink-jobs/kustomization.yaml` (alongside the existing `flink-streaming-sql` ConfigMap); mount `flink_scored_ddl.sql` at `/opt/flink/sql/flink_scored_ddl.sql`

**Checkpoint**: Apply the kustomization and verify `kubectl get tables -n polaris` (or query via `verify_polaris_pyiceberg.py`) shows `transactions_scored` exists before starting the scoring job.

---

## Phase 3: User Story 3 — Real-Time Fraud Scoring Enrichment (Priority: P3)

**Goal**: A second Flink job (`fraud-score-enricher`) reads the `transactions` Iceberg table in streaming mode, enriches each record with a `fraud_probability` score from KServe via non-blocking async HTTP, and writes the result to `transactions_scored`. Records continue flowing even when KServe is temporarily unavailable (error sentinel `–1.0` is written instead of blocking).

**Independent Test**: Start the `fraud-score-enricher` FlinkDeployment; after 60 seconds, query `polaris_catalog.default.transactions_scored` via `scripts/verify_polaris_pyiceberg.py` and confirm rows exist with `fraud_probability` values in `[0.0, 1.0]` (genuine scores) or `–1.0` (sentinel if KServe not yet ready).

### Validation for User Story 3

- [x] T006 [US3] Validate no credentials in source: after implementing T007–T012, run `grep -rn "changeme\|AKIAIOSFODNN\|s3\.access-key" jobs/flink-sql-runner/src/main/java/` — all Polaris and S3 credentials must be absent from Java source; they must come only from env vars via `SqlRunner.applyPolarisCatalogConfigFromEnv()` and `SqlRunner.resolvePolarisOAuthCredential()`

### KServeAsyncFunction.java

- [x] T007 [US3] Create `jobs/flink-sql-runner/src/main/java/org/example/fraud/flink/KServeAsyncFunction.java` with this exact structure:

  **Class header and fields**:
  ```java
  package org.example.fraud.flink;

  import org.apache.flink.configuration.Configuration;
  import org.apache.flink.streaming.api.functions.async.RichAsyncFunction;
  import org.apache.flink.streaming.api.functions.async.ResultFuture;
  import org.apache.flink.types.Row;

  import java.net.URI;
  import java.net.http.HttpClient;
  import java.net.http.HttpRequest;
  import java.net.http.HttpResponse;
  import java.time.Duration;
  import java.util.Collections;
  import java.util.concurrent.CompletableFuture;

  public class KServeAsyncFunction extends RichAsyncFunction<Row, Row> {
      private static final long serialVersionUID = 1L;
      private final String endpoint;
      private transient HttpClient httpClient;  // not serializable — rebuilt in open()

      public KServeAsyncFunction(String endpoint) {
          this.endpoint = endpoint;
      }
  ```

  **`open()` — create HttpClient once per task slot**:
  ```java
      @Override
      public void open(Configuration parameters) {
          httpClient = HttpClient.newBuilder()
              .version(HttpClient.Version.HTTP_1_1)
              .connectTimeout(Duration.ofSeconds(5))
              .build();
      }
  ```

  **`asyncInvoke()` — build payload, fire async request, complete future**:
  ```java
      @Override
      public void asyncInvoke(Row input, ResultFuture<Row> resultFuture) {
          double amount    = ((Number) input.getField("amount")).doubleValue();
          double velocity  = ((Number) input.getField("amount_velocity_5min")).doubleValue();
          double distance  = ((Number) input.getField("distance_from_home_km")).doubleValue();
          int    userId    = ((Number) input.getField("user_id")).intValue();

          String payload = String.format(
              "{\"inputs\":[{\"name\":\"features\",\"shape\":[1,4],\"datatype\":\"FP64\"," +
              "\"data\":[[%.6f,%.6f,%.6f,%d]]}]}",
              amount, velocity, distance, userId);

          HttpRequest request = HttpRequest.newBuilder()
              .uri(URI.create(endpoint))
              .header("Content-Type", "application/json")
              .POST(HttpRequest.BodyPublishers.ofString(payload))
              .timeout(Duration.ofSeconds(10))
              .build();

          httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofString())
              .whenComplete((response, error) -> {
                  double prob = (error == null && response.statusCode() == 200)
                      ? parseV2Response(response.body())
                      : -1.0;
                  resultFuture.complete(Collections.singletonList(Row.join(input, Row.of(prob))));
              });
      }
  ```

  **`timeout()` — emit sentinel on async timeout**:
  ```java
      @Override
      public void timeout(Row input, ResultFuture<Row> resultFuture) {
          resultFuture.complete(Collections.singletonList(Row.join(input, Row.of(-1.0))));
      }
  ```

  **`parseV2Response()` — extract the first output value without a JSON library**:
  ```java
      static double parseV2Response(String body) {
          // Expects: {"outputs":[{"name":"output-0","shape":[1],"datatype":"FP64","data":[0.87]}]}
          int idx = body.indexOf("\"data\":[");
          if (idx < 0) return -1.0;
          int start = body.indexOf('[', idx + 7) + 1;
          int end   = body.indexOf(']', start);
          if (start <= 0 || end <= start) return -1.0;
          try {
              return Double.parseDouble(body.substring(start, end).trim());
          } catch (NumberFormatException e) {
              return -1.0;
          }
      }
  }
  ```

### ModelScorerJob.java

- [x] T008 [US3] Create `jobs/flink-sql-runner/src/main/java/org/example/fraud/flink/ModelScorerJob.java`:

  **Imports and constants**:
  ```java
  package org.example.fraud.flink;

  import org.apache.flink.api.java.typeutils.RowTypeInfo;
  import org.apache.flink.streaming.api.datastream.AsyncDataStream;
  import org.apache.flink.streaming.api.datastream.DataStream;
  import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
  import org.apache.flink.table.api.DataTypes;
  import org.apache.flink.table.api.EnvironmentSettings;
  import org.apache.flink.table.api.Schema;
  import org.apache.flink.table.api.Table;
  import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
  import org.apache.flink.types.Row;

  import java.util.concurrent.TimeUnit;

  public final class ModelScorerJob {

      private static final String KSERVE_ENDPOINT_DEFAULT =
          "http://fraud-detector.kubeflow-user-example-com.svc.cluster.local" +
          "/v2/models/fraud-detector/infer";

      private static final int MAX_CONCURRENT_REQUESTS = 100;
      private static final long ASYNC_TIMEOUT_SECONDS  = 30L;

      // Polaris catalog DDL — credentials are injected by SqlRunner.applyPolarisCatalogConfigFromEnv
      private static final String CATALOG_DDL =
          "CREATE CATALOG IF NOT EXISTS polaris_catalog WITH (\n" +
          "  'type' = 'iceberg',\n" +
          "  'catalog-type' = 'rest',\n" +
          "  'uri' = 'http://polaris.polaris.svc.cluster.local:8181/api/catalog',\n" +
          "  'warehouse' = 'quickstart_catalog',\n" +
          "  'credential' = 'root:changeme',\n" +   // overridden by applyPolarisCatalogConfigFromEnv
          "  'scope' = 'PRINCIPAL_ROLE:ALL'\n" +
          ")";
  ```

  **`main()` — environment setup, catalog, DataStream pipeline**:
  ```java
      public static void main(String[] args) throws Exception {
          String kserveEndpoint = System.getenv()
              .getOrDefault("KSERVE_ENDPOINT", KSERVE_ENDPOINT_DEFAULT);

          StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
          StreamTableEnvironment tEnv = StreamTableEnvironment.create(
              env, EnvironmentSettings.newInstance().inStreamingMode().build());

          // Register catalog with credential injection (reuses SqlRunner logic)
          tEnv.executeSql(SqlRunner.applyPolarisCatalogConfigFromEnv(CATALOG_DDL));
          tEnv.executeSql("CREATE DATABASE IF NOT EXISTS `polaris_catalog`.`default`");

          // Read transactions as incremental streaming DataStream
          // /*+ OPTIONS(...) */ hint enables Iceberg incremental append reads
          Table txTable = tEnv.sqlQuery(
              "SELECT transaction_id, user_id, amount, merchant, lat, lon, ts, " +
              "       processing_time, amount_velocity_5min, distance_from_home_km " +
              "FROM `polaris_catalog`.`default`.`transactions` " +
              "/*+ OPTIONS('streaming'='true', 'monitor-interval'='5s') */");

          DataStream<Row> txStream = tEnv.toDataStream(txTable, Row.class);

          // Async KServe enrichment — unordered for maximum throughput
          DataStream<Row> scoredStream = AsyncDataStream.unorderedWait(
              txStream,
              new KServeAsyncFunction(kserveEndpoint),
              ASYNC_TIMEOUT_SECONDS,
              TimeUnit.SECONDS,
              MAX_CONCURRENT_REQUESTS);

          // Define output schema (input columns + fraud_probability)
          Schema outputSchema = Schema.newBuilder()
              .column("transaction_id",        DataTypes.STRING())
              .column("user_id",               DataTypes.INT())
              .column("amount",                DataTypes.DOUBLE())
              .column("merchant",              DataTypes.STRING())
              .column("lat",                   DataTypes.DOUBLE())
              .column("lon",                   DataTypes.DOUBLE())
              .column("ts",                    DataTypes.TIMESTAMP(3))
              .column("processing_time",       DataTypes.TIMESTAMP(3))
              .column("amount_velocity_5min",  DataTypes.DOUBLE())
              .column("distance_from_home_km", DataTypes.DOUBLE())
              .column("fraud_probability",     DataTypes.DOUBLE())
              .build();

          tEnv.fromDataStream(scoredStream, outputSchema)
              .executeInsert("`polaris_catalog`.`default`.`transactions_scored`");
      }
  }
  ```

### pom.xml — additional manifest entry

- [x] T009 [US3] Update `jobs/flink-sql-runner/pom.xml`: in the `maven-shade-plugin` configuration, the current `ManifestResourceTransformer` sets `mainClass` to `SqlRunner`. Since the FAT JAR must support two entry points, add an explicit `MANIFEST.MF` attribute `Additional-Main-Classes: org.example.fraud.flink.ModelScorerJob` via a second `<manifestEntry>` (this does not change the default main class, it just documents the second entry point); the `FlinkDeployment` specifies `entryClass` explicitly so the default `mainClass` is irrelevant at runtime

### JAR rebuild and image reload

- [x] T010 [US3] Rebuild the FAT JAR and reload into Minikube:
  ```bash
  cd jobs/flink-sql-runner && mvn clean package -DskipTests
  # Verify both classes are in the JAR:
  jar tf target/flink-sql-runner-*.jar | grep -E "SqlRunner|KServeAsync|ModelScorer"
  # Rebuild Docker image
  cd /path/to/repo
  docker build -t flink-sql-runner:1.20.5 apps/base/flink-jobs
  minikube image load flink-sql-runner:1.20.5
  ```

### FlinkDeployment — fraud-score-enricher

- [x] T011 [US3] Append a second `FlinkDeployment` resource named `fraud-score-enricher` to `apps/base/flink-jobs/resources.yaml`; base it on the existing `sample-fraud-stream` spec with these differences:
  - `metadata.name: fraud-score-enricher`
  - `spec.job.entryClass: org.example.fraud.flink.ModelScorerJob`
  - `spec.job.args: []` (no SQL file path needed — logic is in Java)
  - Add env var `KSERVE_ENDPOINT` with value `http://fraud-detector.kubeflow-user-example-com.svc.cluster.local/v2/models/fraud-detector/infer` to both jobManager and taskManager `podTemplate.spec.containers[0].env`
  - Keep all existing Secret refs (`minio-flink-s3-credentials`, `polaris-flink-oauth`, `polaris-bootstrap-credentials`) — same pattern as `sample-fraud-stream`
  - Keep `taskmanager.numberOfTaskSlots: "2"` and checkpoint config (same S3 paths)
  - Remove the `flink-streaming-sql` volume mount (not needed) — replace with no volume mounts

- [x] T012 [US3] Verify the `fraud-score-enricher` FlinkDeployment starts: `kubectl get flinkdeployment -n flink-system fraud-score-enricher` shows `LIFECYCLE_STATE=RUNNING`; check job manager logs: `kubectl logs -n flink-system -l app=fraud-score-enricher,component=jobmanager | tail -30` — should show `KServeAsyncFunction open()` called and first async requests being dispatched

### End-to-end verification

- [x] T013 [US3] Run the Polaris verification script to confirm scored rows are appearing:
  ```bash
  python scripts/verify_polaris_pyiceberg.py
  # Extend the script or run an ad-hoc check:
  # table = catalog.load_table("default.transactions_scored")
  # df = table.scan(limit=10).to_pandas()
  # print(df[["transaction_id", "fraud_probability"]])
  # Assert: len(df) > 0 and df["fraud_probability"].between(-1.0, 1.0).all()
  ```
  Confirm that: (a) rows exist in `transactions_scored`; (b) `fraud_probability` is in `[0.0, 1.0]` for successful KServe calls or exactly `-1.0` for error sentinel rows; (c) all columns from `transactions` are present alongside `fraud_probability`

**Checkpoint**: US3 complete. `transactions_scored` Iceberg table contains rows with non-null `fraud_probability`; Flink job shows no restarts; KServe error rate < 5% under normal conditions.

---

## Phase 4: Polish & Cross-Cutting Concerns

- [x] T014 [P] Update `apps/base/flink-jobs/README.md` with a new section "Model Scoring Job (`fraud-score-enricher`)": describe the job purpose, how it reads from `transactions`, async concurrency limit (100), KServe endpoint env var, error sentinel value (`-1.0`), and how to verify scored records in Iceberg; add a note that the synchronous upgrade path is to implement `AsyncDataStream.orderedWait()` if strict ordering is required

- [x] T015 [P] Add a `// FOLLOW-UP 2026-Q3: Consider switching to AsyncDataStream.orderedWait() if downstream consumers require strict event ordering; benchmark throughput difference` comment in `ModelScorerJob.java` after the `AsyncDataStream.unorderedWait()` call

- [x] T016 [P] Update `docs/runbooks/verify-kafka-flink-iceberg.md` to add a verification step for `transactions_scored`: query the table via `verify_polaris_pyiceberg.py` and confirm `fraud_probability` column exists and has non-null values; add this as the final step in the end-to-end smoke test sequence

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can run immediately
- **Foundational (Phase 2)**: Depends on Phase 1; `transactions_scored` table must exist before `ModelScorerJob` writes to it — create via T003–T005 before starting the FlinkDeployment
- **US3 (Phase 3)**: Depends on Phase 2 (table exists) and KServe InferenceService being Ready
- **Polish (Phase 4)**: Depends on Phase 3 and at least one successful end-to-end verification run

### Within Phase 3

- T007 (`KServeAsyncFunction.java`) and T008 (`ModelScorerJob.java`) are independent Java files — author in parallel
- T009 (`pom.xml` update) is independent of T007/T008 — can be done in parallel
- T010 (rebuild + reload) requires T007, T008, T009 all complete
- T011 (FlinkDeployment) can be drafted while T007–T010 are in progress (different file)
- T012 (verify deployment) requires T010 and T011
- T013 (end-to-end check) requires T012 and `transactions_scored` table populated from T003–T005

### Parallel Opportunities

```bash
# Phase 1 — both checks in parallel:
T001 AsyncDataStream classpath check  +  T002 Iceberg streaming syntax note

# Phase 3 — three independent files, author together:
T007 KServeAsyncFunction.java  +  T008 ModelScorerJob.java  +  T009 pom.xml
# Then merge at T010 (rebuild needs all three)

# FlinkDeployment can be drafted while JAR is building:
T010 mvn build (runs for ~2 min)  ||  T011 draft FlinkDeployment YAML

# Phase 4 — all three polish tasks touch different files:
T014 flink-jobs/README.md  +  T015 comment in ModelScorerJob.java  +  T016 verify runbook
```

---

## Implementation Strategy

### MVP (Scoring job running and writing to Iceberg)

1. T003–T005: Create `transactions_scored` Iceberg table via one-shot SQL Job
2. T007: Implement `KServeAsyncFunction.java`
3. T008: Implement `ModelScorerJob.java`
4. T010: Rebuild JAR, reload image
5. T011: Add `fraud-score-enricher` FlinkDeployment
6. T013: Verify rows in `transactions_scored` with `fraud_probability` values
7. **STOP and VALIDATE**: query the table; confirm fraud probability scores are present

### Full Delivery

1. MVP above
2. T009: pom.xml manifest entry (cosmetic but clean)
3. T012: Verify Flink job logs show no restarts
4. T014–T016: READMEs and runbook updated

---

## Notes

- `KServeAsyncFunction.httpClient` is `transient` and rebuilt in `open()` — `HttpClient` is not Java-serializable and must not be included in Flink's state snapshot
- `AsyncDataStream.unorderedWait()` is used (not `orderedWait`) for maximum throughput — downstream Iceberg writes do not depend on strict event ordering; if a consumer requires event-time ordering, switch to `orderedWait` at the cost of increased buffering
- The `parseV2Response()` method uses simple string scanning instead of a JSON library to avoid adding Jackson to the FAT JAR (Jackson is already on the Flink cluster classpath but not guaranteed in the user classloader); if the KServe response format changes, upgrade to `com.fasterxml.jackson.databind.ObjectMapper` — Jackson is available as a `provided` dependency
- `fraud_probability = -1.0` is the error sentinel for: (a) KServe HTTP error, (b) non-200 response, (c) async timeout, (d) response parse failure — downstream queries can use `WHERE fraud_probability >= 0.0` to filter valid scores
- The `transactions_scored` Iceberg table must exist before `ModelScorerJob` starts; the one-shot `create-transactions-scored-table` Kubernetes Job (T004) handles this; if Flux applies the FlinkDeployment before the Job completes, the job will retry automatically due to `upgradeMode: last-state` checkpointing
- `minikube image load` replaces the in-cluster image tag — always reload after every JAR rebuild; the FlinkDeployment will not pull the updated image unless the pod is restarted (`kubectl delete pod -n flink-system -l app=fraud-score-enricher`)
