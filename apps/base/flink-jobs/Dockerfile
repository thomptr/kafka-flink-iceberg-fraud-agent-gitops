# =============================================================================
# Build context MUST be the repository root — not this directory.
#   cd jobs/flink-sql-runner && mvn -DskipTests package && cd ../..
#   docker build -f apps/base/flink-jobs/Dockerfile -t flink-sql-runner:1.20 .
# (Tag must match FlinkDeployment spec.image.)
# Verify: docker run --rm flink-sql-runner:1.20 sh -c 'test -f /docker-entrypoint.orig.sh && echo OK'
# If you run `docker build` from apps/base/flink-jobs, COPY paths below will fail.
# =============================================================================
FROM flink:1.20.3-java17
USER root
RUN mkdir -p /opt/flink/sql /opt/flink/plugins/s3-fs-hadoop /opt/flink/lib \
  && curl -fsSL -o /opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop.jar \
  https://repo1.maven.org/maven2/org/apache/flink/flink-s3-fs-hadoop/1.20.3/flink-s3-fs-hadoop-1.20.3.jar \
  # Iceberg's sink metrics use Flink's Dropwizard wrapper plus metrics-core. Keep both on the
  # shared Flink lib classpath so they resolve from the parent loader instead of the user-jar loader.
  && curl -fsSL -o /opt/flink/lib/flink-metrics-dropwizard-1.20.3.jar \
  https://repo1.maven.org/maven2/org/apache/flink/flink-metrics-dropwizard/1.20.3/flink-metrics-dropwizard-1.20.3.jar \
  && curl -fsSL -o /opt/flink/lib/metrics-core-3.2.6.jar \
  https://repo1.maven.org/maven2/io/dropwizard/metrics/metrics-core/3.2.6/metrics-core-3.2.6.jar
# Wrap the upstream entrypoint so FLINK_PROPERTIES is set from AWS_* (operator may omit FLINK_PROPERTIES env).
RUN mv /docker-entrypoint.sh /docker-entrypoint.orig.sh
COPY apps/base/flink-jobs/docker-entrypoint-wrapper.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh /docker-entrypoint.orig.sh \
  && chown flink:flink /docker-entrypoint.sh /docker-entrypoint.orig.sh
COPY jobs/flink-sql-runner/target/flink-sql-runner-0.1.0-SNAPSHOT.jar /opt/flink/lib/sql-runner.jar
# Default SQL in image; GitOps uses a ConfigMap mount at the same path when deployed.
COPY apps/base/flink-jobs/flink_streaming_job.sql /opt/flink/sql/flink_streaming_job.sql
USER flink
