#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="${ROOT_DIR}/proto"
PROTO_FILE="${PROTO_DIR}/runtime_agent.proto"

OUT_RUNTIME="${ROOT_DIR}/saki-runtime/src/saki_runtime/grpc_gen"
OUT_API="${ROOT_DIR}/saki-api/src/saki_api/grpc_gen"

mkdir -p "${OUT_RUNTIME}" "${OUT_API}"

python3 -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${OUT_RUNTIME}" \
  --grpc_python_out="${OUT_RUNTIME}" \
  "${PROTO_FILE}"

python3 -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${OUT_API}" \
  --grpc_python_out="${OUT_API}" \
  "${PROTO_FILE}"

