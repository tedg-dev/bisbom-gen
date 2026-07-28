# OmniBOR Analysis — Build & Push
#
# Registry owner is auto-detected from your git remote origin.
# Override: export GHCR_OWNER=myuser  (or set in .env)

-include .env

GHCR_OWNER ?= $(shell git remote get-url origin 2>/dev/null | sed -n 's|.*github\.com[:/]\([^/]*\)/.*|\1|p')
REGISTRY   := ghcr.io/$(GHCR_OWNER)
TAG        ?= dev

.PHONY: help login info sidecar push clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  %-24s %s\n", $$1, $$2}'

info: ## Show resolved registry and tag
	@echo "GHCR_OWNER = $(GHCR_OWNER)"
	@echo "REGISTRY   = $(REGISTRY)"
	@echo "TAG        = $(TAG)"
	@echo "  $(REGISTRY)/omnibor-sidecar:$(TAG)"

login: ## Login to GHCR (requires GITHUB_TOKEN env var or gh auth)
	@echo $(GITHUB_TOKEN) | docker login ghcr.io -u $(GHCR_OWNER) --password-stdin 2>/dev/null \
		|| gh auth token | docker login ghcr.io -u $(GHCR_OWNER) --password-stdin

sidecar: ## Build sidecar image
	docker build --target sidecar -f docker/Dockerfile -t $(REGISTRY)/omnibor-sidecar:$(TAG) .

push: sidecar ## Build and push sidecar image
	docker push $(REGISTRY)/omnibor-sidecar:$(TAG)

clean: ## Remove local dev-tagged image
	docker rmi $(REGISTRY)/omnibor-sidecar:$(TAG) 2>/dev/null || true
