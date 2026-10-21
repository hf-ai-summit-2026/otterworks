package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

const testSecret = "router-test-secret"

func newTestRouter(t *testing.T, routes []Route, cbCfg CircuitBreakerConfig) http.Handler {
	t.Helper()
	prefixes := make([]string, 0, len(routes))
	for _, r := range routes {
		prefixes = append(prefixes, r.Prefix)
	}
	router := NewRouter(RouterConfig{
		Routes:        routes,
		CBManager:     NewCircuitBreakerManager(cbCfg),
		Logger:        zerolog.Nop(),
		EnableTracing: true,
	})
	return middleware.JWTAuth(middleware.JWTConfig{
		Secret:              testSecret,
		ProtectedPrefixPath: prefixes,
	})(router)
}

func signToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(testSecret))
	require.NoError(t, err)
	return tok
}

func decodeBody(t *testing.T, rec *httptest.ResponseRecorder) map[string]string {
	t.Helper()
	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	return body
}

func TestRouter_UnknownRouteReturnsJSON404(t *testing.T) {
	h := newTestRouter(t, []Route{{Prefix: "/api/v1/files", TargetURL: "http://127.0.0.1:0"}}, defaultTestConfig())

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/nope", nil))

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.Equal(t, "route not found", decodeBody(t, rec)["error"])
}

func TestRouter_ProxiesPathAndForwardsUserID(t *testing.T) {
	cases := []struct {
		name   string
		claims middleware.JWTClaims
		want   string
	}{
		{"subject claim", middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "user-sub"}}, "user-sub"},
		{"user_id fallback", middleware.JWTClaims{UserID: "user-legacy"}, "user-legacy"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var gotPath, gotUser string
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotPath = r.URL.Path
				gotUser = r.Header.Get("X-User-ID")
				w.WriteHeader(http.StatusOK)
			}))
			defer backend.Close()

			h := newTestRouter(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, defaultTestConfig())

			for _, path := range []string{"/api/v1/files/", "/api/v1/files/abc/download"} {
				req := httptest.NewRequest(http.MethodGet, path, nil)
				req.Header.Set("Authorization", "Bearer "+signToken(t, tc.claims))
				rec := httptest.NewRecorder()
				h.ServeHTTP(rec, req)

				assert.Equal(t, http.StatusOK, rec.Code)
				assert.Equal(t, path, gotPath)
				assert.Equal(t, tc.want, gotUser)
			}
		})
	}
}

func TestRouter_UnreachableBackendReturns502(t *testing.T) {
	backend := httptest.NewServer(http.NotFoundHandler())
	target := backend.URL
	backend.Close()

	h := newTestRouter(t, []Route{{Prefix: "/api/v1/search", TargetURL: target}}, defaultTestConfig())

	req := httptest.NewRequest(http.MethodGet, "/api/v1/search/q", nil)
	req.Header.Set("Authorization", "Bearer "+signToken(t, middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u"}}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Equal(t, map[string]string{"error": "service unavailable", "target": "/api/v1/search"}, decodeBody(t, rec))
}

func TestRouter_OpenCircuitReturns503(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer backend.Close()

	cbCfg := CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.5}
	h := newTestRouter(t, []Route{{Prefix: "/api/v1/audit", TargetURL: backend.URL}}, cbCfg)
	token := signToken(t, middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u"}})

	send := func() *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/audit/events", nil)
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}

	for i := 0; i < 5; i++ {
		assert.Equal(t, http.StatusInternalServerError, send().Code)
	}

	rec := send()
	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	assert.Equal(t, map[string]string{
		"error":   "service temporarily unavailable",
		"service": "/api/v1/audit",
		"reason":  "circuit breaker open",
	}, decodeBody(t, rec))
}
