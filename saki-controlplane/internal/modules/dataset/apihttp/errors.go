package apihttp

import (
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
)

func badRequestError(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusBadRequest,
		Response: openapi.ErrorResponse{
			Code:    "bad_request",
			Message: message,
		},
	}
}
