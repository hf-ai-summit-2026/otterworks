package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

const testJWTSecret = "router-test-secret"

type capturedRequest struct {
	Path   string
	UserID string
}

func newBackend(t *testing.T, captured *capturedRequest) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured.Path = r.URL.Path
		captured.UserID = r.Header.Get("X-User-ID")
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func newTestRouter(routes ...Route) http.Handler {
	r := NewRouter(RouterConfig{
		Routes:    routes,
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})
	return middleware.JWTAuth(middleware.JWTConfig{Secret: testJWTSecret})(r)
}

func signToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(testJWTSecret))
	require.NoError(t, err)
	return tok
}

func doRequest(h http.Handler, path, token string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestRouter_PreservesFullPathToBackend(t *testing.T) {
	var got capturedRequest
	backend := newBackend(t, &got)
	h := newTestRouter(Route{Prefix: "/api/v1/files", TargetURL: backend.URL})

	token := signToken(t, middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u-1"}})
	rec := doRequest(h, "/api/v1/files/abc/download", token)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/files/abc/download", got.Path)
}

func TestRouter_ForwardsSubjectAsUserID(t *testing.T) {
	var got capturedRequest
	backend := newBackend(t, &got)
	h := newTestRouter(Route{Prefix: "/api/v1/files", TargetURL: backend.URL})

	token := signToken(t, middleware.JWTClaims{
		UserID:           "legacy-id",
		RegisteredClaims: jwt.RegisteredClaims{Subject: "sub-id"},
	})
	rec := doRequest(h, "/api/v1/files/", token)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "sub-id", got.UserID)
}

func TestRouter_FallsBackToUserIDClaim(t *testing.T) {
	var got capturedRequest
	backend := newBackend(t, &got)
	h := newTestRouter(Route{Prefix: "/api/v1/files", TargetURL: backend.URL})

	token := signToken(t, middleware.JWTClaims{UserID: "legacy-id"})
	rec := doRequest(h, "/api/v1/files/", token)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "legacy-id", got.UserID)
}

func TestRouter_UnknownRouteReturnsJSON404(t *testing.T) {
	var got capturedRequest
	backend := newBackend(t, &got)
	h := newTestRouter(Route{Prefix: "/api/v1/files", TargetURL: backend.URL})

	token := signToken(t, middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u-1"}})
	rec := doRequest(h, "/api/v1/nope", token)

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	assert.Equal(t, "route not found", body["error"])
}

func TestRouter_UnreachableBackendReturnsJSON502(t *testing.T) {
	backend := httptest.NewServer(http.NotFoundHandler())
	deadURL := backend.URL
	backend.Close()
	h := newTestRouter(Route{Prefix: "/api/v1/files", TargetURL: deadURL})

	token := signToken(t, middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u-1"}})
	rec := doRequest(h, "/api/v1/files/", token)

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	assert.Equal(t, "service unavailable", body["error"])
	assert.Equal(t, "/api/v1/files", body["target"])
}
