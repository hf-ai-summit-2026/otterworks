package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidate_RequiresJWTSecret(t *testing.T) {
	assert.Error(t, (&Config{}).Validate())
	assert.NoError(t, (&Config{JWTSecret: "s3cret"}).Validate())
}

// unsetEnv clears keys for the duration of the test, restoring them afterwards.
func unsetEnv(t *testing.T, keys ...string) {
	t.Helper()
	for _, k := range keys {
		t.Setenv(k, "")
		require.NoError(t, os.Unsetenv(k))
	}
}

func TestLoad_Defaults(t *testing.T) {
	unsetEnv(t, "PORT", "RATE_LIMIT_RPS", "CB_FAILURE_RATIO", "CB_MAX_REQUESTS",
		"SHUTDOWN_TIMEOUT_SECONDS", "CORS_ALLOWED_ORIGINS", "REDIS_HOST", "REDIS_PORT", "JWT_SECRET")

	cfg := Load()

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, "", cfg.RedisAddr())
	assert.Error(t, cfg.Validate(), "JWT_SECRET has no default")
}

func TestLoad_EmptySliceVarFallsBack(t *testing.T) {
	t.Setenv("CORS_ALLOWED_METHODS", "")

	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, Load().CORSAllowedMethods)
}

func TestLoad_Overrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CB_MAX_REQUESTS", "7")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("JWT_SECRET", "s3cret")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, 250, cfg.RateLimitRPS)
	assert.Equal(t, 0.25, cfg.CBFailureRatio)
	assert.Equal(t, uint32(7), cfg.CBMaxRequests)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.NoError(t, cfg.Validate())
}

func TestLoad_InvalidNumbersFallBack(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "lots")
	t.Setenv("CB_FAILURE_RATIO", "high")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
}

func TestRedisAddr(t *testing.T) {
	assert.Equal(t, "", (&Config{RedisPort: "6379"}).RedisAddr(), "empty host disables chaos")
	assert.Equal(t, "redis:6380", (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr())
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:         "http://auth",
		FileServiceURL:         "http://file",
		DocumentServiceURL:     "http://doc",
		CollabServiceURL:       "http://collab",
		NotificationServiceURL: "http://notif",
		SearchServiceURL:       "http://search",
		AnalyticsServiceURL:    "http://analytics",
		AdminServiceURL:        "http://admin",
		AuditServiceURL:        "http://audit",
		ReportServiceURL:       "http://report",
	}

	routes := cfg.ServiceRoutes()

	require.Len(t, routes, 15)
	for prefix, want := range map[string]string{
		"/api/v1/auth":        "http://auth",
		"/api/v1/settings":    "http://auth",
		"/api/v1/folders":     "http://file",
		"/api/v1/templates":   "http://doc",
		"/socket.io":          "http://collab",
		"/api/v1/preferences": "http://notif",
		"/api/v1/reports":     "http://report",
	} {
		assert.Equal(t, want, routes[prefix], prefix)
	}
	for prefix, url := range routes {
		assert.NotEmpty(t, url, "route %s has no backend", prefix)
	}
}
