#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(CDPATH="" cd "$(dirname "$0")/.." && pwd)"
RENDER_ONLY="${1:-}"
PATHS=(
  "clusters/minikube"
  "infrastructure/controllers/minikube"
  "infrastructure/configs/minikube"
  "apps/minikube"
)

for rel in "${PATHS[@]}"; do
  path="$REPO_ROOT/$rel"
  echo "[validate] rendering $rel"
  rendered="$(mktemp)"
  kustomize build "$path" > "$rendered"
  if [[ "$RENDER_ONLY" != "--render-only" ]] && command -v kubeconform >/dev/null 2>&1; then
    kubeconform -summary -ignore-missing-schemas "$rendered"
  fi
  rm -f "$rendered"
done

if [[ "$RENDER_ONLY" != "--render-only" ]] && command -v yamllint >/dev/null 2>&1; then
  yamllint "$REPO_ROOT"
fi

if [[ "$RENDER_ONLY" != "--render-only" ]] && command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source "$REPO_ROOT" --no-git --verbose
fi

echo "[validate] completed"
