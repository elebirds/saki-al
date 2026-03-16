package apihttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	ogenhttp "github.com/ogen-go/ogen/http"
)

func mapError(err error) *openapi.ErrorResponseStatusCode {
	switch {
	case errors.Is(err, ogenhttp.ErrNotImplemented):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusNotImplemented,
			Response: openapi.ErrorResponse{
				Code:    "not_implemented",
				Message: "operation not implemented",
			},
		}
	default:
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusInternalServerError,
			Response: openapi.ErrorResponse{
				Code:    "internal_error",
				Message: "internal server error",
			},
		}
	}
}

func writeMappedError(_ context.Context, w http.ResponseWriter, _ *http.Request, err error) {
	mapped := mapError(err)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(mapped.StatusCode)
	_ = json.NewEncoder(w).Encode(mapped.Response)
}
