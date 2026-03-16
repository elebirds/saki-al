GO ?= go
BIN_DIR ?= bin

.PHONY: test fmt vet build-public-api build-runtime run-public-api run-runtime

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
