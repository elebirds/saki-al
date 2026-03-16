package auth

import (
	"context"
	"encoding/json"
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

func Middleware(authenticator *accessapp.Authenticator) func(http.Handler) http.Handler {
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

			next.ServeHTTP(w, r.WithContext(WithClaims(r.Context(), claims)))
		})
	}
}

func writeUnauthorized(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusUnauthorized)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"code":    "unauthorized",
		"message": "invalid bearer token",
	})
}
