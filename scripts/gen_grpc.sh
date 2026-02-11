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

uv run --with grpcio-tools==1.78.* python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$API_OUT" \
  --grpc_python_out="$API_OUT" \
  "$PROTO_FILE"

uv run --with grpcio-tools==1.78.* python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$EXEC_OUT" \
  --grpc_python_out="$EXEC_OUT" \
  "$PROTO_FILE"

for out in "$API_OUT" "$EXEC_OUT"; do
  pb2_grpc_file="$out/runtime_control_pb2_grpc.py"
  python3 -c "
from pathlib import Path

path = Path('$pb2_grpc_file')
text = path.read_text(encoding='utf-8')
text = text.replace('import runtime_control_pb2 as runtime__control__pb2', 'from . import runtime_control_pb2 as runtime__control__pb2')
path.write_text(text, encoding='utf-8')
"
done

echo "gRPC stubs generated for saki-api and saki-executor"
