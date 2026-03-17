GO ?= go
BIN_DIR ?= bin
GO_BIN ?= $(shell $(GO) env GOPATH)/bin
GOPROXY ?= https://proxy.golang.org,direct
OGEN_VERSION ?= v1.20.1
BUF_VERSION ?= v1.66.1
SQLC_VERSION ?= v1.30.0
OGEN_BIN ?= $(shell command -v ogen 2>/dev/null)
BUF_BIN ?= $(shell command -v buf 2>/dev/null)
SQLC_BIN ?= $(shell command -v sqlc 2>/dev/null)

.PHONY: test test-runtime test-access fmt vet build-public-api build-runtime run-public-api run-runtime gen gen-openapi gen-proto gen-sqlc check-gen smoke-public-api ci

test:
	$(GO) test ./...

test-runtime:
	$(GO) test ./internal/modules/runtime/...

test-access:
	$(GO) test ./internal/app/config ./internal/app/bootstrap ./internal/modules/access/... -v
	$(MAKE) smoke-public-api

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
ifneq ($(strip $(OGEN_BIN)),)
	$(OGEN_BIN) --clean --target internal/gen/openapi --package openapi api/openapi/public-api.yaml
else
	GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/ogen-go/ogen/cmd/ogen@$(OGEN_VERSION) --clean --target internal/gen/openapi --package openapi api/openapi/public-api.yaml
endif

gen-proto:
	mkdir -p internal/gen/proto
ifneq ($(strip $(BUF_BIN)),)
	$(BUF_BIN) generate
else
	PATH="$(GO_BIN):$$PATH" GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION) generate
endif

gen-sqlc:
	mkdir -p internal/gen/sqlc
ifneq ($(strip $(SQLC_BIN)),)
	$(SQLC_BIN) generate -f db/sqlc.yaml
else
	GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/sqlc-dev/sqlc/cmd/sqlc@$(SQLC_VERSION) generate -f db/sqlc.yaml
endif

check-gen:
	$(MAKE) gen
	git diff --exit-code -- internal/gen

smoke-public-api:
	$(GO) test ./internal/modules/system/apihttp -run TestPublicAPISmoke -v

ci: check-gen smoke-public-api test vet
