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

  public static void main(String[] args) throws Exception {
    if (args.length < 1) {
      System.err.println("Usage: SqlRunner <path-to.sql>");
      System.exit(1);
    }
    Path sqlPath = Path.of(args[0]);
    String raw = Files.readString(sqlPath);
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
}
