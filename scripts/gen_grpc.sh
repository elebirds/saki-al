#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$ROOT_DIR/proto"
PROTO_FILE="$PROTO_DIR/runtime_control.proto"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

API_OUT="$ROOT_DIR/saki-api/src/saki_api/grpc_gen"
EXEC_OUT="$ROOT_DIR/saki-executor/src/saki_executor/grpc_gen"

mkdir -p "$API_OUT" "$EXEC_OUT"

uv run --with grpcio-tools python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$API_OUT" \
  --grpc_python_out="$API_OUT" \
  "$PROTO_FILE"

uv run --with grpcio-tools python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$EXEC_OUT" \
  --grpc_python_out="$EXEC_OUT" \
  "$PROTO_FILE"

echo "gRPC stubs generated for saki-api and saki-executor"
