package org.example.fraud.flink;

import java.util.concurrent.TimeUnit;

import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.streaming.api.datastream.AsyncDataStream;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.table.api.DataTypes;
import org.apache.flink.table.api.EnvironmentSettings;
import org.apache.flink.table.api.Schema;
import org.apache.flink.table.api.Table;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.types.Row;

/**
 * Reads the {@code transactions} Iceberg table as a streaming source, calls the KServe fraud
 * detection endpoint via Flink Async I/O, and writes the enriched records (including
 * {@code fraud_probability}) to {@code transactions_scored}.
 *
 * <p>The {@code transactions_scored} table must exist before this job starts. Create it by
 * running the {@code create-transactions-scored-table} Kubernetes Job first.
 *
 * <p>Configuration via environment variables:
 * <ul>
 *   <li>{@code KSERVE_ENDPOINT} — KServe V2 inference URL (optional, has a default)
 *   <li>Polaris OAuth ({@code POLARIS_OAUTH_CREDENTIAL} etc.) — same as SqlRunner
 *   <li>MinIO S3 ({@code AWS_ACCESS_KEY_ID}, {@code AWS_SECRET_ACCESS_KEY}) — same as SqlRunner
 * </ul>
 */
public final class ModelScorerJob {

    private static final String KSERVE_ENDPOINT_DEFAULT =
            "http://fraud-detector.kubeflow-user-example-com.svc.cluster.local"
            + "/v2/models/fraud-detector/infer";

    private static final int MAX_CONCURRENT_REQUESTS = 100;
    private static final long ASYNC_TIMEOUT_SECONDS = 30L;

    // Placeholder credential is replaced at runtime by SqlRunner.applyPolarisCatalogConfigFromEnv.
    private static final String CATALOG_DDL =
            "CREATE CATALOG polaris_catalog WITH (\n"
            + "  'type' = 'iceberg',\n"
            + "  'catalog-type' = 'rest',\n"
            + "  'uri' = 'http://polaris.polaris.svc.cluster.local:8181/api/catalog',\n"
            + "  'warehouse' = 'quickstart_catalog',\n"
            + "  'credential' = 'root:changeme',\n"
            + "  'scope' = 'PRINCIPAL_ROLE:ALL'\n"
            + ")";

    public static void main(String[] args) throws Exception {
        String kserveEndpoint = System.getenv().getOrDefault("KSERVE_ENDPOINT", KSERVE_ENDPOINT_DEFAULT);

        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        EnvironmentSettings settings = EnvironmentSettings.newInstance().inStreamingMode().build();
        StreamTableEnvironment tEnv = StreamTableEnvironment.create(env, settings);

        // Register Polaris catalog; credentials are injected from env vars via SqlRunner helper.
        String catalogDdl = SqlRunner.applyPolarisCatalogConfigFromEnv(CATALOG_DDL);
        tEnv.executeSql(catalogDdl);

        // Streaming read from Iceberg via the table hint OPTIONS override.
        Table txTable = tEnv.sqlQuery(
                "SELECT * FROM `polaris_catalog`.`default`.`transactions`"
                + " /*+ OPTIONS('streaming'='true', 'monitor-interval'='5s') */");

        DataStream<Row> txStream = tEnv.toDataStream(txTable);

        DataStream<Row> scoredStream = AsyncDataStream.unorderedWait(
                txStream,
                new KServeAsyncFunction(kserveEndpoint),
                ASYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS,
                MAX_CONCURRENT_REQUESTS);

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
        // TODO: add Prometheus counter for fraud_probability == -1.0 (KServe errors) once
        // a MetricGroup is wired through KServeAsyncFunction.getRuntimeContext().
    }
}
