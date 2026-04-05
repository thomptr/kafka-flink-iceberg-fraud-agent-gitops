#!/usr/bin/env bash
# The Flink Kubernetes Operator mounts /opt/flink/conf from a ConfigMap (read-only). The upstream
# docker-entrypoint merges FLINK_PROPERTIES into those files via config-parser-utils.sh, which fails
# silently when the tree is not writable — so fs.s3a.access.key never lands in Flink/Hadoop config.
# We copy config into a writable /tmp tree, append S3 keys, and point FLINK_CONF_DIR there.
# AWS_* come from the same Kubernetes secret as the FlinkDeployment podTemplate.
set -euo pipefail

if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  MERGE_DIR="/tmp/flink-conf-s3-merge.$$"
  rm -rf "${MERGE_DIR}"
  mkdir -p "${MERGE_DIR}"
  chmod 700 "${MERGE_DIR}"

  shopt -s nullglob
  for src in /opt/flink/conf/*; do
    base=$(basename "${src}")
    cp -L "${src}" "${MERGE_DIR}/${base}"
  done
  shopt -u nullglob

  append_s3_keys() {
    local f=$1
    if [[ -f "${MERGE_DIR}/${f}" ]]; then
      printf '\nfs.s3a.access.key: %s\nfs.s3a.secret.key: %s\n' \
        "${AWS_ACCESS_KEY_ID}" "${AWS_SECRET_ACCESS_KEY}" >>"${MERGE_DIR}/${f}"
      chmod 600 "${MERGE_DIR}/${f}"
    fi
  }

  if [[ -f "${MERGE_DIR}/flink-conf.yaml" ]]; then
    append_s3_keys flink-conf.yaml
  elif [[ -f "${MERGE_DIR}/config.yaml" ]]; then
    append_s3_keys config.yaml
  fi

  export FLINK_CONF_DIR="${MERGE_DIR}"

  # Still export for any code path that merges from env (envsubst in upstream entrypoint).
  EXTRA="fs.s3a.access.key: ${AWS_ACCESS_KEY_ID}
fs.s3a.secret.key: ${AWS_SECRET_ACCESS_KEY}"
  if [[ -n "${FLINK_PROPERTIES:-}" ]]; then
    export FLINK_PROPERTIES="${FLINK_PROPERTIES}
${EXTRA}"
  else
    export FLINK_PROPERTIES="${EXTRA}"
  fi
fi

exec /docker-entrypoint.orig.sh "$@"
