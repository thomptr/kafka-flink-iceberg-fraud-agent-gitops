# =============================================================================
# Build context MUST be the repository root — not this directory.
#   cd jobs/flink-sql-runner && mvn -DskipTests package && cd ../..
#   docker build -f apps/base/flink-jobs/Dockerfile -t flink-sql-runner:1.18 .
# If you run `docker build` from apps/base/flink-jobs, COPY paths below will fail.
# =============================================================================
FROM flink:1.18
USER root
RUN mkdir -p /opt/flink/sql /opt/flink/plugins/s3-fs-hadoop \
  && curl -fsSL -o /opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop.jar \
  https://repo1.maven.org/maven2/org/apache/flink/flink-s3-fs-hadoop/1.18.1/flink-s3-fs-hadoop-1.18.1.jar
COPY jobs/flink-sql-runner/target/flink-sql-runner-0.1.0-SNAPSHOT.jar /opt/flink/lib/sql-runner.jar
# Default SQL in image; GitOps uses a ConfigMap mount at the same path when deployed.
COPY apps/base/flink-jobs/flink_streaming_job.sql /opt/flink/sql/flink_streaming_job.sql
USER flink
