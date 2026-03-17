package auth

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
)

type contextKey string

const claimsContextKey contextKey = "access.claims"

func WithClaims(ctx context.Context, claims *accessapp.Claims) context.Context {
	return context.WithValue(ctx, claimsContextKey, claims)
}

func ClaimsFromContext(ctx context.Context) (*accessapp.Claims, bool) {
	claims, ok := ctx.Value(claimsContextKey).(*accessapp.Claims)
	return claims, ok && claims != nil
}

func Middleware(authenticator *accessapp.Authenticator, store accessapp.Store) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			header := r.Header.Get("Authorization")
			if header == "" {
				next.ServeHTTP(w, r)
				return
			}

			token, ok := strings.CutPrefix(header, "Bearer ")
			if !ok || token == "" {
				writeUnauthorized(w)
				return
			}

			claims, err := authenticator.ParseToken(token)
			if err != nil {
				writeUnauthorized(w)
				return
			}

			resolvedClaims, err := resolveClaims(r.Context(), store, claims)
			switch {
			case errors.Is(err, accessapp.ErrUnauthorized):
				writeUnauthorized(w)
				return
			case err != nil:
				writeInternalError(w)
				return
			}

			next.ServeHTTP(w, r.WithContext(WithClaims(r.Context(), resolvedClaims)))
		})
	}
}

func resolveClaims(ctx context.Context, store accessapp.Store, claims *accessapp.Claims) (*accessapp.Claims, error) {
	principal, err := store.GetPrincipalByID(ctx, claims.PrincipalID)
	if err != nil {
		return nil, err
	}
	if principal == nil || principal.IsDisabled() {
		return nil, accessapp.ErrUnauthorized
	}
	if principal.SubjectKey != claims.UserID {
		return nil, accessapp.ErrUnauthorized
	}

	permissions, err := store.ListPermissions(ctx, principal.ID)
	if err != nil {
		return nil, err
	}

	return &accessapp.Claims{
		PrincipalID: principal.ID,
		UserID:      principal.SubjectKey,
		Permissions: permissions,
		ExpiresAt:   claims.ExpiresAt,
	}, nil
}

func writeUnauthorized(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusUnauthorized)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"code":    "unauthorized",
		"message": "invalid bearer token",
	})
}

func writeInternalError(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusInternalServerError)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"code":    "internal_error",
		"message": "internal server error",
	})
}
