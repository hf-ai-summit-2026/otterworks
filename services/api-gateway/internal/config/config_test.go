package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var envKeys = []string{
	"PORT", "LOG_LEVEL",
	"AUTH_SERVICE_URL", "FILE_SERVICE_URL", "DOCUMENT_SERVICE_URL", "COLLAB_SERVICE_URL",
	"NOTIFICATION_SERVICE_URL", "SEARCH_SERVICE_URL", "ANALYTICS_SERVICE_URL",
	"ADMIN_SERVICE_URL", "AUDIT_SERVICE_URL", "REPORT_SERVICE_URL",
	"REDIS_HOST", "REDIS_PORT", "RATE_LIMIT_RPS", "JWT_SECRET", "JWT_PEER_SECRET",
	"CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_METHODS", "CORS_ALLOWED_HEADERS", "CORS_MAX_AGE",
	"SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_INTERVAL_SECONDS", "CB_TIMEOUT_SECONDS",
	"CB_FAILURE_RATIO",
}

// clearEnv unsets every variable Load reads for the duration of the test.
func clearEnv(t *testing.T) {
	t.Helper()
	for _, k := range envKeys {
		t.Setenv(k, "")
		require.NoError(t, os.Unsetenv(k))
	}
}

func TestLoad_Defaults(t *testing.T) {
	clearEnv(t)

	cfg := Load()

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, "info", cfg.LogLevel)
	assert.Equal(t, "http://auth-service:8081", cfg.AuthServiceURL)
	assert.Equal(t, "http://file-service:8082", cfg.FileServiceURL)
	assert.Equal(t, "http://document-service:8083", cfg.DocumentServiceURL)
	assert.Equal(t, "http://collab-service:8084", cfg.CollabServiceURL)
	assert.Equal(t, "http://notification-service:8086", cfg.NotificationServiceURL)
	assert.Equal(t, "http://search-service:8087", cfg.SearchServiceURL)
	assert.Equal(t, "http://analytics-service:8088", cfg.AnalyticsServiceURL)
	assert.Equal(t, "http://admin-service:8089", cfg.AdminServiceURL)
	assert.Equal(t, "http://audit-service:8090", cfg.AuditServiceURL)
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
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
}

func TestLoad_EnvOverrides(t *testing.T) {
	clearEnv(t)
	t.Setenv("PORT", "9090")
	t.Setenv("FILE_SERVICE_URL", "http://files.local:1234")
	t.Setenv("REDIS_HOST", "redis")
	t.Setenv("REDIS_PORT", "6380")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("JWT_SECRET", "s3cret")
	t.Setenv("JWT_PEER_SECRET", "peer")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_MAX_REQUESTS", "3")
	t.Setenv("CB_FAILURE_RATIO", "0.25")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, "http://files.local:1234", cfg.FileServiceURL)
	assert.Equal(t, "redis:6380", cfg.RedisAddr())
	assert.Equal(t, 7, cfg.RateLimitRPS)
	assert.Equal(t, "s3cret", cfg.JWTSecret)
	assert.Equal(t, "peer", cfg.JWTPeerSecret)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(3), cfg.CBMaxRequests)
	assert.Equal(t, 0.25, cfg.CBFailureRatio)
}

func TestLoad_InvalidNumbersFallBackToDefaults(t *testing.T) {
	clearEnv(t)
	t.Setenv("RATE_LIMIT_RPS", "lots")
	t.Setenv("CB_FAILURE_RATIO", "most")
	t.Setenv("CORS_ALLOWED_METHODS", "")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, cfg.CORSAllowedMethods)
}

func TestValidate_RequiresJWTSecret(t *testing.T) {
	cfg := &Config{}
	err := cfg.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "JWT_SECRET")

	cfg.JWTSecret = "s3cret"
	assert.NoError(t, cfg.Validate())
}

func TestRedisAddr_EmptyHostDisablesChaos(t *testing.T) {
	cfg := &Config{RedisPort: "6379"}
	assert.Equal(t, "", cfg.RedisAddr())
}

func TestServiceRoutes(t *testing.T) {
	clearEnv(t)
	cfg := Load()

	routes := cfg.ServiceRoutes()

	assert.Equal(t, map[string]string{
		"/api/v1/auth":          cfg.AuthServiceURL,
		"/api/v1/files":         cfg.FileServiceURL,
		"/api/v1/folders":       cfg.FileServiceURL,
		"/api/v1/documents":     cfg.DocumentServiceURL,
		"/api/v1/templates":     cfg.DocumentServiceURL,
		"/api/v1/collab":        cfg.CollabServiceURL,
		"/socket.io":            cfg.CollabServiceURL,
		"/api/v1/notifications": cfg.NotificationServiceURL,
		"/api/v1/preferences":   cfg.NotificationServiceURL,
		"/api/v1/search":        cfg.SearchServiceURL,
		"/api/v1/analytics":     cfg.AnalyticsServiceURL,
		"/api/v1/admin":         cfg.AdminServiceURL,
		"/api/v1/audit":         cfg.AuditServiceURL,
		"/api/v1/reports":       cfg.ReportServiceURL,
		"/api/v1/settings":      cfg.AuthServiceURL,
	}, routes)
}
