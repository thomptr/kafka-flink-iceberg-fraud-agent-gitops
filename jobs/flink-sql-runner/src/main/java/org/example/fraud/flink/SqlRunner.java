package org.example.fraud.flink;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.stream.Collectors;

import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.table.api.EnvironmentSettings;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.table.api.TableResult;

/**
 * Executes SQL statements from a file (semicolon-separated). Intended for GitOps-mounted
 * scripts that create catalogs/tables and run a streaming INSERT.
 */
public final class SqlRunner {

  /**
   * Matches the sample credential in {@code flink_streaming_job.sql}. When any of {@code
   * POLARIS_OAUTH_CREDENTIAL}, {@code POLARIS_CLIENT_ID}+{@code POLARIS_CLIENT_SECRET}, or {@code
   * POLARIS_BOOTSTRAP_CREDENTIALS} is set (e.g. from a Secret), the catalog line is rewritten so
   * Polaris OAuth matches {@code polaris-bootstrap-credentials} in the cluster.
   */
  private static final String SAMPLE_CREDENTIAL_SNIPPET = "'credential' = 'root:changeme'";
  private static final String DEFAULT_MINIO_ENDPOINT = "http://minio.minio.svc.cluster.local:9000";
  private static final String DEFAULT_REGION = "us-east-1";

  public static void main(String[] args) throws Exception {
    if (args.length < 1) {
      System.err.println("Usage: SqlRunner <path-to.sql>");
      System.exit(1);
    }
    Path sqlPath = Path.of(args[0]);
    String raw = applyPolarisCatalogConfigFromEnv(Files.readString(sqlPath));
    String stripped =
        Arrays.stream(raw.split("\n"))
            .filter(line -> !line.trim().startsWith("--"))
            .collect(Collectors.joining("\n"));

    StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
    EnvironmentSettings settings =
        EnvironmentSettings.newInstance().inStreamingMode().build();
    StreamTableEnvironment tEnv = StreamTableEnvironment.create(env, settings);

    String[] statements = stripped.split(";");
    TableResult last = null;
    for (String statement : statements) {
      String stmt = statement.trim();
      if (stmt.isEmpty()) {
        continue;
      }
      last = tEnv.executeSql(stmt);
    }
    if (last != null && last.getJobClient().isPresent()) {
      last.getJobClient().get().getJobExecutionResult();
    }
  }

  static String applyPolarisCatalogConfigFromEnv(String sql) {
    if (!sql.contains(SAMPLE_CREDENTIAL_SNIPPET)) {
      return sql;
    }

    String credential = resolvePolarisOAuthCredential();
    String replacement =
        credential == null || credential.isEmpty()
            ? SAMPLE_CREDENTIAL_SNIPPET
            : "'credential' = '" + credential.replace("'", "''") + "'";

    String accessKey = firstNonEmpty(System.getenv("POLARIS_S3_ACCESS_KEY_ID"), System.getenv("AWS_ACCESS_KEY_ID"));
    String secretKey =
        firstNonEmpty(
            System.getenv("POLARIS_S3_SECRET_ACCESS_KEY"), System.getenv("AWS_SECRET_ACCESS_KEY"));
    if (accessKey != null && secretKey != null) {
      String endpoint =
          firstNonEmpty(System.getenv("POLARIS_S3_ENDPOINT"), System.getenv("POLARIS_MINIO_ENDPOINT"));
      if (endpoint == null) {
        endpoint = DEFAULT_MINIO_ENDPOINT;
      }
      String region =
          firstNonEmpty(System.getenv("POLARIS_REGION"), System.getenv("AWS_REGION"));
      if (region == null) {
        region = DEFAULT_REGION;
      }
      String pathStyle =
          firstNonEmpty(System.getenv("POLARIS_S3_PATH_STYLE_ACCESS"), "true");
      replacement +=
          ",\n"
              + "  'header.X-Iceberg-Access-Delegation' = '',\n"
              + "  'io-impl' = 'org.apache.iceberg.aws.s3.S3FileIO',\n"
              + "  's3.endpoint' = '"
              + endpoint.replace("'", "''")
              + "',\n"
              + "  's3.path-style-access' = '"
              + pathStyle.replace("'", "''")
              + "',\n"
              + "  's3.access-key-id' = '"
              + accessKey.replace("'", "''")
              + "',\n"
              + "  's3.secret-access-key' = '"
              + secretKey.replace("'", "''")
              + "',\n"
              + "  'client.region' = '"
              + region.replace("'", "''")
              + "'";
    }

    return sql.replace(SAMPLE_CREDENTIAL_SNIPPET, replacement);
  }

  /**
   * Returns {@code client_id:client_secret} for Iceberg REST/Polaris, or {@code null} if unset.
   *
   * <p>Priority: {@code POLARIS_OAUTH_CREDENTIAL}, then {@code POLARIS_CLIENT_ID} + {@code
   * POLARIS_CLIENT_SECRET}, then {@code POLARIS_BOOTSTRAP_CREDENTIALS} ({@code REALM,id,secret}).
   */
  static String resolvePolarisOAuthCredential() {
    String direct = System.getenv("POLARIS_OAUTH_CREDENTIAL");
    if (direct != null && !direct.isEmpty()) {
      return direct;
    }
    String id = System.getenv("POLARIS_CLIENT_ID");
    String secret = System.getenv("POLARIS_CLIENT_SECRET");
    if (id != null && secret != null && !id.isEmpty() && !secret.isEmpty()) {
      return id + ":" + secret;
    }
    String bootstrap = System.getenv("POLARIS_BOOTSTRAP_CREDENTIALS");
    if (bootstrap != null && !bootstrap.isEmpty()) {
      String[] parts = bootstrap.split(",", 3);
      if (parts.length == 3) {
        return parts[1] + ":" + parts[2];
      }
    }
    return null;
  }

  static String firstNonEmpty(String... values) {
    for (String value : values) {
      if (value != null && !value.isEmpty()) {
        return value;
      }
    }
    return null;
  }
}
