package apihttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	ogenhttp "github.com/ogen-go/ogen/http"
	"github.com/ogen-go/ogen/validate"
)

type badRequestError struct {
	message string
}

func (e *badRequestError) Error() string {
	return e.message
}

func newBadRequest(message string) error {
	return &badRequestError{message: message}
}

func mapError(err error) *openapi.ErrorResponseStatusCode {
	var validateErr *validate.Error
	var badRequestErr *badRequestError
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
	case errors.Is(err, identityapp.ErrInvalidCredentials), errors.Is(err, identityapp.ErrInvalidRefreshSession), errors.Is(err, identityapp.ErrRefreshSessionReplayDetected):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusUnauthorized,
			Response: openapi.ErrorResponse{
				Code:    "unauthorized",
				Message: "invalid credentials or session",
			},
		}
	case errors.Is(err, identityapp.ErrInvalidUserInput),
		errors.Is(err, authorizationapp.ErrInvalidRoleInput),
		errors.Is(err, authorizationapp.ErrInvalidRolePermission),
		errors.Is(err, authorizationapp.ErrInvalidRoleScope),
		errors.Is(err, authorizationapp.ErrInvalidResourceInput),
		errors.Is(err, authorizationapp.ErrInvalidResourceType),
		errors.Is(err, authorizationapp.ErrResourceRoleNotAssignable):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusBadRequest,
			Response: openapi.ErrorResponse{
				Code:    "bad_request",
				Message: err.Error(),
			},
		}
	case errors.Is(err, identityapp.ErrUserNotFound),
		errors.Is(err, authorizationapp.ErrRoleNotFound),
		errors.Is(err, authorizationapp.ErrResourceNotFound),
		errors.Is(err, authorizationapp.ErrResourceMembershipNotFound):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusNotFound,
			Response: openapi.ErrorResponse{
				Code:    "not_found",
				Message: err.Error(),
			},
		}
	case errors.Is(err, identityapp.ErrUserAlreadyExists), errors.Is(err, authorizationapp.ErrRoleAlreadyExists):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusConflict,
			Response: openapi.ErrorResponse{
				Code:    "already_exists",
				Message: err.Error(),
			},
		}
	case errors.Is(err, authorizationapp.ErrRoleImmutable):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusConflict,
			Response: openapi.ErrorResponse{
				Code:    "conflict",
				Message: err.Error(),
			},
		}
	case errors.Is(err, authorizationapp.ErrLastSuperAdmin):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusConflict,
			Response: openapi.ErrorResponse{
				Code:    "conflict",
				Message: err.Error(),
			},
		}
	case errors.Is(err, authorizationapp.ErrResourceOwnerImmutable):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusConflict,
			Response: openapi.ErrorResponse{
				Code:    "conflict",
				Message: err.Error(),
			},
		}
	case errors.Is(err, identityapp.ErrSelfRegistrationDisabled):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusForbidden,
			Response: openapi.ErrorResponse{
				Code:    "self_registration_disabled",
				Message: "self registration is disabled",
			},
		}
	case errors.Is(err, systemapp.ErrAlreadyInitialized):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusConflict,
			Response: openapi.ErrorResponse{
				Code:    "already_initialized",
				Message: "system is already initialized",
			},
		}
	case errors.Is(err, systemapp.ErrNotInitialized):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusConflict,
			Response: openapi.ErrorResponse{
				Code:    "not_initialized",
				Message: "system setup is required",
			},
		}
	case errors.Is(err, systemapp.ErrInvalidSettingValue):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusBadRequest,
			Response: openapi.ErrorResponse{
				Code:    "bad_request",
				Message: err.Error(),
			},
		}
	case errors.As(err, &badRequestErr):
		return &openapi.ErrorResponseStatusCode{
			StatusCode: http.StatusBadRequest,
			Response: openapi.ErrorResponse{
				Code:    "bad_request",
				Message: badRequestErr.Error(),
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
