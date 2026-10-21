package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNormalizePath(t *testing.T) {
	cases := map[string]string{
		"/api/v1/auth/login":            "/api/v1/auth",
		"/api/v1/files":                 "/api/v1/files",
		"/api/v1/files/123/download":    "/api/v1/files",
		"/api/v1/documents/abc":         "/api/v1/documents",
		"/api/v1/collab/rooms":          "/api/v1/collab",
		"/api/v1/notifications/unread":  "/api/v1/notifications",
		"/api/v1/search?q=x":            "/api/v1/search",
		"/api/v1/analytics/events":      "/api/v1/analytics",
		"/api/v1/admin/users":           "/api/v1/admin",
		"/api/v1/audit/events":          "/api/v1/audit",
		"/api/v1/folders/1":             "other",
		"/api/v1/reports":               "other",
		"/health":                       "other",
		"/":                             "other",
		"":                              "other",
		"/api/v1/au":                    "other",
		"/api/v1/authorize-placeholder": "/api/v1/auth",
	}
	for in, want := range cases {
		assert.Equal(t, want, normalizePath(in), "path %q", in)
	}
}

func TestMetrics_PassesThroughResponse(t *testing.T) {
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
		_, _ = w.Write([]byte("short and stout"))
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/files/1", nil))

	assert.Equal(t, http.StatusTeapot, rec.Code)
	assert.Equal(t, "short and stout", rec.Body.String())
}
