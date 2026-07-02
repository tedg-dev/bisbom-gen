# OmniBOR Container Images — Build & Push
#
# Registry owner is auto-detected from your git remote origin.
# Override: export GHCR_OWNER=myuser  (or set in .env)

-include .env

GHCR_OWNER ?= $(shell git remote get-url origin 2>/dev/null | sed -n 's|.*github\.com[:/]\([^/]*\)/.*|\1|p')
REGISTRY   := ghcr.io/$(GHCR_OWNER)
TAG        ?= dev

IMAGES := omnibor-sidecar omnibor-operator omnibor-spdx-indexing omnibor-sbom-tree

.PHONY: help images login push clean $(IMAGES)

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  %-24s %s\n", $$1, $$2}'

info: ## Show resolved registry and tag
	@echo "GHCR_OWNER = $(GHCR_OWNER)"
	@echo "REGISTRY   = $(REGISTRY)"
	@echo "TAG        = $(TAG)"
	@echo ""
	@for img in $(IMAGES); do echo "  $(REGISTRY)/$$img:$(TAG)"; done

login: ## Login to GHCR (requires GITHUB_TOKEN env var or gh auth)
	@echo $(GITHUB_TOKEN) | docker login ghcr.io -u $(GHCR_OWNER) --password-stdin 2>/dev/null \
		|| gh auth token | docker login ghcr.io -u $(GHCR_OWNER) --password-stdin

# ── Individual image targets ──

omnibor-sidecar: ## Build sidecar image
	docker build --target sidecar -f docker/Dockerfile -t $(REGISTRY)/$@:$(TAG) .

omnibor-operator: ## Build operator image
	docker build -f operator/Dockerfile -t $(REGISTRY)/$@:$(TAG) operator/

omnibor-spdx-indexing: ## Build spdx-indexing image
	docker build -f spdx-indexing/Dockerfile -t $(REGISTRY)/$@:$(TAG) spdx-indexing/

omnibor-sbom-tree: ## Build sbom-tree image
	docker build -f sbom-tree/Dockerfile -t $(REGISTRY)/$@:$(TAG) sbom-tree/

# ── Aggregate targets ──

images: $(IMAGES) ## Build all images

push: images ## Build and push all images
	@for img in $(IMAGES); do \
		echo "Pushing $(REGISTRY)/$$img:$(TAG)"; \
		docker push $(REGISTRY)/$$img:$(TAG); \
	done

push-%: % ## Build and push a single image (e.g., make push-omnibor-operator)
	docker push $(REGISTRY)/$*:$(TAG)

clean: ## Remove local dev-tagged images
	@for img in $(IMAGES); do \
		docker rmi $(REGISTRY)/$$img:$(TAG) 2>/dev/null || true; \
	done
