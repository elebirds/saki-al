GO ?= go
BIN_DIR ?= bin
GO_BIN ?= $(shell $(GO) env GOPATH)/bin
GOPROXY ?= https://proxy.golang.org,direct
BUF_VERSION ?= v1.66.1
BUF_BIN ?= $(shell command -v buf 2>/dev/null)

.PHONY: test build-agent gen-proto check-runtime-proto

test:
	$(GO) test ./...

build-agent:
	mkdir -p $(BIN_DIR)
	CGO_ENABLED=0 $(GO) build -o $(BIN_DIR)/agent ./cmd/agent

gen-proto:
	mkdir -p internal/gen
ifneq ($(strip $(BUF_BIN)),)
	$(BUF_BIN) generate
else
	PATH="$(GO_BIN):$$PATH" GOWORK=off GOPROXY=$(GOPROXY) $(GO) run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION) generate
endif

check-runtime-proto:
	@for rel in runtime/v1/agent_control.proto runtime/v1/agent_ingress.proto runtime/v1/agent_events.proto worker/v1/worker.proto; do \
		left=$$(mktemp); \
		right=$$(mktemp); \
		sed '/^option go_package = /d' api/proto/$$rel > $$left; \
		sed '/^option go_package = /d' ../saki-controlplane/api/proto/$$rel > $$right; \
		diff -u $$right $$left; \
		rm -f $$left $$right; \
	done
