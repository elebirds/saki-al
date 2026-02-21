#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$ROOT_DIR/proto"
RUNTIME_PROTO="$PROTO_DIR/runtime_control.proto"
ADMIN_PROTO="$PROTO_DIR/dispatcher_admin.proto"
DOMAIN_PROTO="$PROTO_DIR/runtime_domain.proto"
ALL_PROTO_FILES=("$RUNTIME_PROTO" "$ADMIN_PROTO" "$DOMAIN_PROTO")
IR_PROTO_DIR="$ROOT_DIR/shared/saki-ir/proto"
IR_ANNOTATION_PROTO="$IR_PROTO_DIR/saki/ir/v1/annotation_ir.proto"
IR_MANIFEST_PROTO="$IR_PROTO_DIR/saki/ir/v1/dataset_manifest_ir.proto"
IR_PROTO_FILES=("$IR_ANNOTATION_PROTO" "$IR_MANIFEST_PROTO")
GRPC_TOOLS_VERSION="1.78.0"
GRPC_VERSION="1.78.0"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

API_OUT="$ROOT_DIR/saki-api/src/saki_api/grpc_gen"
EXEC_OUT="$ROOT_DIR/saki-executor/src/saki_executor/grpc_gen"
DISP_OUT_ROOT="$ROOT_DIR/saki-dispatcher/internal/gen"
DISP_RUNTIME_OUT="$DISP_OUT_ROOT/runtimecontrolv1"
DISP_ADMIN_OUT="$DISP_OUT_ROOT/dispatcheradminv1"
DISP_DOMAIN_OUT="$DISP_OUT_ROOT/runtimedomainv1"
IR_PY_OUT="$ROOT_DIR/shared/saki-ir/python/src/saki_ir/proto"
IR_GO_OUT="$ROOT_DIR/shared/saki-ir/go/gen"

mkdir -p "$API_OUT" "$EXEC_OUT" "$DISP_RUNTIME_OUT" "$DISP_ADMIN_OUT" "$DISP_DOMAIN_OUT" "$IR_PY_OUT" "$IR_GO_OUT"

uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$API_OUT" \
  --grpc_python_out="$API_OUT" \
  "${ALL_PROTO_FILES[@]}"

uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$EXEC_OUT" \
  --grpc_python_out="$EXEC_OUT" \
  "$RUNTIME_PROTO"

uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
  -I "$IR_PROTO_DIR" \
  --python_out="$IR_PY_OUT" \
  "${IR_PROTO_FILES[@]}"

export PATH="$HOME/go/bin:$PATH"
if command -v protoc-gen-go >/dev/null 2>&1 && command -v protoc-gen-go-grpc >/dev/null 2>&1; then
  rm -f "$DISP_RUNTIME_OUT"/*.go "$DISP_ADMIN_OUT"/*.go "$DISP_DOMAIN_OUT"/*.go
  rm -f "$IR_GO_OUT"/annotationirv1/*.go "$IR_GO_OUT"/manifestirv1/*.go
  rm -rf "$IR_GO_OUT"/saki
  rm -rf "$IR_GO_OUT"/gen

  uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --go_out="$DISP_RUNTIME_OUT" \
    --go_opt=paths=source_relative \
    --go-grpc_out="$DISP_RUNTIME_OUT" \
    --go-grpc_opt=paths=source_relative \
    "$RUNTIME_PROTO"

  uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --go_out="$DISP_ADMIN_OUT" \
    --go_opt=paths=source_relative \
    --go-grpc_out="$DISP_ADMIN_OUT" \
    --go-grpc_opt=paths=source_relative \
    "$ADMIN_PROTO"

  uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --go_out="$DISP_DOMAIN_OUT" \
    --go_opt=paths=source_relative \
    --go-grpc_out="$DISP_DOMAIN_OUT" \
    --go-grpc_opt=paths=source_relative \
    "$DOMAIN_PROTO"

  uv run --with "grpcio-tools==${GRPC_TOOLS_VERSION}" --with "grpcio==${GRPC_VERSION}" python -m grpc_tools.protoc \
    -I "$IR_PROTO_DIR" \
    --go_out="$IR_GO_OUT" \
    --go_opt=paths=import \
    --go_opt=module=github.com/saki-ai/saki/shared/saki-ir/go/gen \
    "${IR_PROTO_FILES[@]}"

  echo "generated Go stubs for saki-dispatcher"
else
  echo "skip Go stubs generation: protoc-gen-go or protoc-gen-go-grpc not found"
fi

for out in "$API_OUT" "$EXEC_OUT"; do
  python3 -c "
from pathlib import Path

out_dir = Path('$out')
for path in out_dir.glob('*_pb2_grpc.py'):
    text = path.read_text(encoding='utf-8')
    text = text.replace('import runtime_control_pb2 as runtime__control__pb2', 'from . import runtime_control_pb2 as runtime__control__pb2')
    text = text.replace('import dispatcher_admin_pb2 as dispatcher__admin__pb2', 'from . import dispatcher_admin_pb2 as dispatcher__admin__pb2')
    text = text.replace('import runtime_domain_pb2 as runtime__domain__pb2', 'from . import runtime_domain_pb2 as runtime__domain__pb2')
    path.write_text(text, encoding='utf-8')
"
done

echo "gRPC stubs generated for saki-api/saki-executor and saki-ir"
