package publicapi

import (
	"net/http"
	"strings"
)

type RemovedRoute struct {
	Method      string
	PathPattern string
}

var RemovedLegacyRoutes = []RemovedRoute{
	{Method: http.MethodGet, PathPattern: "/roles/permission-catalog"},
	{Method: http.MethodGet, PathPattern: "/permissions/catalog"},
	{Method: http.MethodGet, PathPattern: "/runtime/executors"},
	{Method: http.MethodPost, PathPattern: "/system/setup"},
	{Method: http.MethodGet, PathPattern: "/roles/users/{principal_id}/roles"},
}

func WithRemovedRoutes(next http.Handler, routes ...RemovedRoute) http.Handler {
	matchers := make([]removedRouteMatcher, 0, len(routes))
	for _, route := range routes {
		matchers = append(matchers, removedRouteMatcher{
			method:   route.Method,
			segments: splitPath(route.PathPattern),
		})
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		for _, matcher := range matchers {
			if matcher.matches(r.Method, r.URL.Path) {
				http.NotFound(w, r)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

type removedRouteMatcher struct {
	method   string
	segments []string
}

func (m removedRouteMatcher) matches(method string, path string) bool {
	if m.method != "" && m.method != method {
		return false
	}

	requestSegments := splitPath(path)
	if len(requestSegments) != len(m.segments) {
		return false
	}

	for idx := range m.segments {
		if isPathParamSegment(m.segments[idx]) {
			continue
		}
		if m.segments[idx] != requestSegments[idx] {
			return false
		}
	}

	return true
}

func splitPath(path string) []string {
	trimmed := strings.Trim(path, "/")
	if trimmed == "" {
		return nil
	}
	return strings.Split(trimmed, "/")
}

func isPathParamSegment(segment string) bool {
	// 关键设计：已退役路由数量很少，这里只支持 `{param}` 级别的整段匹配，
	// 既能覆盖 `/roles/users/{principal_id}/roles` 这类旧 alias，又避免引入新的路由树依赖。
	return strings.HasPrefix(segment, "{") && strings.HasSuffix(segment, "}") && len(segment) > 2
}
