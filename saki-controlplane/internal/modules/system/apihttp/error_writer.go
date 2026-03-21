package apihttp

import (
	"context"
	"encoding/json"
	"net/http"
)

// 错误写回单独留在 writer 文件，避免错误分类表和 HTTP 输出细节继续混写。
func writeMappedError(_ context.Context, w http.ResponseWriter, _ *http.Request, err error) {
	mapped := mapError(err)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(mapped.StatusCode)
	_ = json.NewEncoder(w).Encode(mapped.Response)
}
