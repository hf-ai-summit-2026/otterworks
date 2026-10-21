package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var configEnvKeys = []string{
	"PORT", "LOG_LEVEL",
	"AUTH_SERVICE_URL", "FILE_SERVICE_URL", "DOCUMENT_SERVICE_URL", "COLLAB_SERVICE_URL",
	"NOTIFICATION_SERVICE_URL", "SEARCH_SERVICE_URL", "ANALYTICS_SERVICE_URL",
	"ADMIN_SERVICE_URL", "AUDIT_SERVICE_URL", "REPORT_SERVICE_URL",
	"REDIS_HOST", "REDIS_PORT", "RATE_LIMIT_RPS", "JWT_SECRET", "JWT_PEER_SECRET",
	"CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_METHODS", "CORS_ALLOWED_HEADERS", "CORS_MAX_AGE",
	"SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_INTERVAL_SECONDS",
	"CB_TIMEOUT_SECONDS", "CB_FAILURE_RATIO",
}

// clearConfigEnv unsets every variable Load reads, restoring them after the test.
func clearConfigEnv(t *testing.T) {
	t.Helper()
	for _, k := range configEnvKeys {
		t.Setenv(k, "")
		require.NoError(t, os.Unsetenv(k))
	}
}

func TestLoad_Defaults(t *testing.T) {
	clearConfigEnv(t)

	cfg := Load()

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, "info", cfg.LogLevel)
	assert.Equal(t, "http://auth-service:8081", cfg.AuthServiceURL)
	assert.Equal(t, "http://report-service:8091", cfg.ReportServiceURL)
	assert.Equal(t, "", cfg.RedisHost)
	assert.Equal(t, "6379", cfg.RedisPort)
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, "", cfg.JWTSecret)
	assert.Equal(t, "", cfg.JWTPeerSecret)
	assert.Equal(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, cfg.CORSAllowedMethods)
	assert.Equal(t, []string{"Accept", "Authorization", "Content-Type", "X-Request-ID"}, cfg.CORSAllowedHeaders)
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.Equal(t, 60*time.Second, cfg.CBInterval)
	assert.Equal(t, 30*time.Second, cfg.CBTimeout)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_EnvOverrides(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("PORT", "9090")
	t.Setenv("FILE_SERVICE_URL", "http://files.local:1234")
	t.Setenv("REDIS_HOST", "redis.local")
	t.Setenv("REDIS_PORT", "6380")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("JWT_SECRET", "s3cret")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_MAX_REQUESTS", "10")
	t.Setenv("CB_FAILURE_RATIO", "0.25")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, "http://files.local:1234", cfg.FileServiceURL)
	assert.Equal(t, "redis.local", cfg.RedisHost)
	assert.Equal(t, "6380", cfg.RedisPort)
	assert.Equal(t, 250, cfg.RateLimitRPS)
	assert.Equal(t, "s3cret", cfg.JWTSecret)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(10), cfg.CBMaxRequests)
	assert.InDelta(t, 0.25, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_InvalidNumbersFallBackToDefaults(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("RATE_LIMIT_RPS", "lots")
	t.Setenv("CORS_MAX_AGE", "")
	t.Setenv("CB_FAILURE_RATIO", "high")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_EmptyStringAndSliceEnv(t *testing.T) {
	clearConfigEnv(t)
	// An explicitly empty string var is honoured; an empty slice var falls back.
	t.Setenv("LOG_LEVEL", "")
	t.Setenv("CORS_ALLOWED_METHODS", "")

	cfg := Load()

	assert.Equal(t, "", cfg.LogLevel)
	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, cfg.CORSAllowedMethods)
}

func TestValidate(t *testing.T) {
	assert.Error(t, (&Config{}).Validate())
	assert.NoError(t, (&Config{JWTSecret: "x"}).Validate())
}

func TestRedisAddr(t *testing.T) {
	assert.Equal(t, "", (&Config{RedisPort: "6379"}).RedisAddr())
	assert.Equal(t, "redis:6379", (&Config{RedisHost: "redis", RedisPort: "6379"}).RedisAddr())
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
	}, cfg.ServiceRoutes())
}
