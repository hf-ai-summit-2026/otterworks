package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoad_Defaults(t *testing.T) {
	unsetForTest(t, "PORT", "RATE_LIMIT_RPS", "JWT_SECRET", "REDIS_HOST", "REDIS_PORT",
		"CORS_ALLOWED_ORIGINS", "SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_FAILURE_RATIO")

	cfg := Load()

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, "", cfg.JWTSecret)
	assert.Equal(t, "6379", cfg.RedisPort)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
	assert.Contains(t, cfg.CORSAllowedOrigins, "http://localhost:3000")
}

func TestLoad_Overrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, 7, cfg.RateLimitRPS)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.InDelta(t, 0.25, cfg.CBFailureRatio, 1e-9)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
}

func TestLoad_InvalidNumbersFallBack(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CB_FAILURE_RATIO", "abc")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_EmptySliceFallsBack(t *testing.T) {
	t.Setenv("CORS_ALLOWED_METHODS", "")

	cfg := Load()

	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, cfg.CORSAllowedMethods)
}

func TestValidate(t *testing.T) {
	require.Error(t, (&Config{}).Validate())
	require.NoError(t, (&Config{JWTSecret: "s3cret"}).Validate())
}

func TestRedisAddr(t *testing.T) {
	assert.Equal(t, "", (&Config{RedisPort: "6379"}).RedisAddr())
	assert.Equal(t, "redis:6380", (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr())
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{FileServiceURL: "http://files", AuthServiceURL: "http://auth"}
	routes := cfg.ServiceRoutes()

	assert.Equal(t, "http://files", routes["/api/v1/files"])
	assert.Equal(t, "http://files", routes["/api/v1/folders"])
	assert.Equal(t, "http://auth", routes["/api/v1/settings"])
}

// unsetForTest unsets keys for the duration of the test, restoring them afterwards.
func unsetForTest(t *testing.T, keys ...string) {
	t.Helper()
	for _, key := range keys {
		t.Setenv(key, "")
		require.NoError(t, os.Unsetenv(key))
	}
}
