package apihttp

import (
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
)

func unauthorized(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusUnauthorized,
		Response: openapi.ErrorResponse{
			Code:    "unauthorized",
			Message: message,
		},
	}
}

func forbidden(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusForbidden,
		Response: openapi.ErrorResponse{
			Code:    "forbidden",
			Message: message,
		},
	}
}

func badRequest(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusBadRequest,
		Response: openapi.ErrorResponse{
			Code:    "bad_request",
			Message: message,
		},
	}
}

func notFound(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusNotFound,
		Response: openapi.ErrorResponse{
			Code:    "not_found",
			Message: message,
		},
	}
}
