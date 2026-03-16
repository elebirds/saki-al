GO ?= go
BIN_DIR ?= bin
GO_BIN ?= $(shell $(GO) env GOPATH)/bin
GOPROXY ?= https://proxy.golang.org,direct
OGEN_VERSION ?= v1.20.1
BUF_VERSION ?= v1.66.1
SQLC_VERSION ?= v1.30.0

.PHONY: test fmt vet build-public-api build-runtime run-public-api run-runtime gen gen-openapi gen-proto gen-sqlc

test:
	$(GO) test ./...

fmt:
	$(GO) fmt ./...

vet:
	$(GO) vet ./...

build-public-api:
	mkdir -p $(BIN_DIR)
	CGO_ENABLED=0 $(GO) build -o $(BIN_DIR)/public-api ./cmd/public-api

build-runtime:
	mkdir -p $(BIN_DIR)
	CGO_ENABLED=0 $(GO) build -o $(BIN_DIR)/runtime ./cmd/runtime

run-public-api:
	$(GO) run ./cmd/public-api

run-runtime:
	$(GO) run ./cmd/runtime

gen: gen-openapi gen-proto gen-sqlc

gen-openapi:
	mkdir -p internal/gen/openapi
	GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/ogen-go/ogen/cmd/ogen@$(OGEN_VERSION) --clean --target internal/gen/openapi --package openapi api/openapi/public-api.yaml

gen-proto:
	mkdir -p internal/gen/proto
	PATH="$(GO_BIN):$$PATH" GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION) generate

gen-sqlc:
	mkdir -p internal/gen/sqlc
	GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/sqlc-dev/sqlc/cmd/sqlc@$(SQLC_VERSION) generate -f db/sqlc.yaml
