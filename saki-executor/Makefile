UV ?= uv
PYTEST_PATH ?= tests
ROOT_DIR := $(abspath $(CURDIR)/..)

.PHONY: help sync run test check grpc clean

help:
	@echo "Available targets:"
	@echo "  make sync   # install dependencies (including dev extras)"
	@echo "  make run    # run executor"
	@echo "  make test   # run tests"
	@echo "  make check  # alias of test"
	@echo "  make grpc   # regenerate gRPC stubs (all services)"
	@echo "  make clean  # remove local cache artifacts"

sync:
	$(UV) sync --project . --extra dev

run:
	$(UV) run --project . python -m saki_executor.main

test:
	$(UV) run --project . --with pytest --with pytest-asyncio pytest $(PYTEST_PATH)

check: test

grpc:
	bash $(ROOT_DIR)/scripts/gen_grpc.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
