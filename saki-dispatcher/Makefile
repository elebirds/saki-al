GO ?= go
BINARY_NAME ?= saki-dispatcher
BIN_DIR ?= bin
MAIN_PKG ?= ./cmd/dispatcher
ROOT_DIR := $(abspath $(CURDIR)/..)

.PHONY: help run build test fmt vet sqlc grpc clean

help:
	@echo "Available targets:"
	@echo "  make run    # run dispatcher"
	@echo "  make build  # build binary to ./bin"
	@echo "  make test   # run go tests"
	@echo "  make fmt    # format Go code"
	@echo "  make vet    # run go vet"
	@echo "  make sqlc   # regenerate sqlc code"
	@echo "  make grpc   # regenerate gRPC stubs (all services)"
	@echo "  make clean  # remove local build artifacts"

run:
	$(GO) run $(MAIN_PKG)

build:
	mkdir -p $(BIN_DIR)
	CGO_ENABLED=0 $(GO) build -o $(BIN_DIR)/$(BINARY_NAME) $(MAIN_PKG)

test:
	$(GO) test ./...

fmt:
	$(GO) fmt ./...

vet:
	$(GO) vet ./...

sqlc:
	sqlc generate

grpc:
	bash $(ROOT_DIR)/scripts/gen_grpc.sh

clean:
	rm -rf $(BIN_DIR)
