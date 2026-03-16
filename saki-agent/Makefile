GO ?= go
BIN_DIR ?= bin

.PHONY: test build-agent

test:
	$(GO) test ./...

build-agent:
	mkdir -p $(BIN_DIR)
	CGO_ENABLED=0 $(GO) build -o $(BIN_DIR)/agent ./cmd/agent
