package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// unsetEnv clears keys for the duration of the test and restores them afterwards.
func unsetEnv(t *testing.T, keys ...string) {
	t.Helper()
	for _, key := range keys {
		if val, ok := os.LookupEnv(key); ok {
			t.Cleanup(func() { os.Setenv(key, val) })
		}
		os.Unsetenv(key)
	}
}

func TestLoad_Defaults(t *testing.T) {
	unsetEnv(t, "PORT", "LOG_LEVEL", "AUTH_SERVICE_URL", "REDIS_HOST", "REDIS_PORT",
		"RATE_LIMIT_RPS", "JWT_SECRET", "JWT_PEER_SECRET", "CORS_ALLOWED_ORIGINS",
		"CORS_MAX_AGE", "SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS",
		"CB_INTERVAL_SECONDS", "CB_TIMEOUT_SECONDS", "CB_FAILURE_RATIO")

	cfg := Load()

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, "info", cfg.LogLevel)
	assert.Equal(t, "http://auth-service:8081", cfg.AuthServiceURL)
	assert.Equal(t, "", cfg.RedisHost)
	assert.Equal(t, "6379", cfg.RedisPort)
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, "", cfg.JWTSecret)
	assert.Equal(t, "", cfg.JWTPeerSecret)
	assert.Equal(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.Equal(t, 60*time.Second, cfg.CBInterval)
	assert.Equal(t, 30*time.Second, cfg.CBTimeout)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
}

func TestLoad_Overrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("AUTH_SERVICE_URL", "http://auth.local:1234")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("JWT_SECRET", "s3cret")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_MAX_REQUESTS", "3")
	t.Setenv("CB_FAILURE_RATIO", "0.25")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, "http://auth.local:1234", cfg.AuthServiceURL)
	assert.Equal(t, 7, cfg.RateLimitRPS)
	assert.Equal(t, "s3cret", cfg.JWTSecret)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(3), cfg.CBMaxRequests)
	assert.Equal(t, 0.25, cfg.CBFailureRatio)
}

func TestLoad_InvalidNumbersFallBackToDefaults(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CORS_MAX_AGE", "")
	t.Setenv("CB_FAILURE_RATIO", "high")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
}

func TestLoad_EmptySliceFallsBackToDefault(t *testing.T) {
	t.Setenv("CORS_ALLOWED_METHODS", "")

	cfg := Load()

	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, cfg.CORSAllowedMethods)
}

func TestLoad_EmptyStringIsKeptForPlainStrings(t *testing.T) {
	t.Setenv("LOG_LEVEL", "")

	cfg := Load()

	assert.Equal(t, "", cfg.LogLevel)
}

func TestValidate(t *testing.T) {
	err := (&Config{}).Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "JWT_SECRET")

	assert.NoError(t, (&Config{JWTSecret: "x"}).Validate())
}

func TestRedisAddr(t *testing.T) {
	assert.Equal(t, "", (&Config{RedisPort: "6379"}).RedisAddr())
	assert.Equal(t, "redis:6380", (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr())
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:         "auth",
		FileServiceURL:         "file",
		DocumentServiceURL:     "doc",
		CollabServiceURL:       "collab",
		NotificationServiceURL: "notif",
		SearchServiceURL:       "search",
		AnalyticsServiceURL:    "analytics",
		AdminServiceURL:        "admin",
		AuditServiceURL:        "audit",
		ReportServiceURL:       "report",
	}

	routes := cfg.ServiceRoutes()

	assert.Equal(t, map[string]string{
		"/api/v1/auth":          "auth",
		"/api/v1/files":         "file",
		"/api/v1/folders":       "file",
		"/api/v1/documents":     "doc",
		"/api/v1/templates":     "doc",
		"/api/v1/collab":        "collab",
		"/socket.io":            "collab",
		"/api/v1/notifications": "notif",
		"/api/v1/preferences":   "notif",
		"/api/v1/search":        "search",
		"/api/v1/analytics":     "analytics",
		"/api/v1/admin":         "admin",
		"/api/v1/audit":         "audit",
		"/api/v1/reports":       "report",
		"/api/v1/settings":      "auth",
	}, routes)
}
