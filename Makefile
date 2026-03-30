SHELL := /bin/bash

.PHONY: validate validate-render validate-yaml smoke tree

validate: validate-render validate-yaml
	./scripts/validate.sh

validate-render:
	./scripts/validate.sh --render-only

validate-yaml:
	@if command -v yamllint >/dev/null 2>&1; then yamllint .; else echo "yamllint not installed; skipping"; fi

smoke:
	@echo "Run the commands in specs/001-fluxcd-gitops-repo/quickstart.md against a live Minikube cluster."

tree:
	@printf "clusters/minikube -> infrastructure -> apps
"
