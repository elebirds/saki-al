package apihttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	ogenhttp "github.com/ogen-go/ogen/http"
	"github.com/ogen-go/ogen/validate"
)

func mapError(err error) *openapi.ErrorResponseStatusCode {
	var validateErr *validate.Error
	switch {
	case errors.Is(err, accessapp.ErrUnauthorized):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusUnauthorized,
			Response: openapi.ErrorResponse{
				Code:    "unauthorized",
				Message: "authentication required",
			},
		}
	case errors.Is(err, accessapp.ErrForbidden):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusForbidden,
			Response: openapi.ErrorResponse{
				Code:    "forbidden",
				Message: "permission denied",
			},
		}
	case errors.Is(err, ogenhttp.ErrNotImplemented):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusNotImplemented,
			Response: openapi.ErrorResponse{
				Code:    "not_implemented",
				Message: "operation not implemented",
			},
		}
	case errors.As(err, &validateErr):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusBadRequest,
			Response: openapi.ErrorResponse{
				Code:    "bad_request",
				Message: validateErr.Error(),
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
