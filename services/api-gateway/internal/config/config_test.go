package config

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoad_Defaults(t *testing.T) {
	for _, key := range []string{
		"PORT", "RATE_LIMIT_RPS", "JWT_SECRET", "REDIS_HOST", "REDIS_PORT",
		"CORS_ALLOWED_ORIGINS", "SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_FAILURE_RATIO",
	} {
		t.Setenv(key, "")
	}

	cfg := Load()

	assert.Equal(t, "", cfg.Port, "an explicitly empty PORT is honoured, not defaulted")
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
	assert.Contains(t, cfg.CORSAllowedOrigins, "http://localhost:3000")
}

func TestLoad_Overrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("AUTH_SERVICE_URL", "http://auth.local:1234")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, 250, cfg.RateLimitRPS)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.InDelta(t, 0.25, cfg.CBFailureRatio, 1e-9)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, "http://auth.local:1234", cfg.AuthServiceURL)
}

func TestLoad_InvalidNumbersFallBackToDefaults(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CB_FAILURE_RATIO", "abc")
	t.Setenv("CORS_MAX_AGE", "1.5")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
	assert.Equal(t, 300, cfg.CORSMaxAge)
}

func TestValidate(t *testing.T) {
	err := (&Config{}).Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "JWT_SECRET")

	assert.NoError(t, (&Config{JWTSecret: "s3cret"}).Validate())
}

func TestRedisAddr(t *testing.T) {
	assert.Equal(t, "", (&Config{RedisPort: "6379"}).RedisAddr())
	assert.Equal(t, "redis:6380", (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr())
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:     "http://auth",
		FileServiceURL:     "http://file",
		DocumentServiceURL: "http://doc",
		CollabServiceURL:   "http://collab",
	}
	routes := cfg.ServiceRoutes()

	assert.Len(t, routes, 15)
	assert.Equal(t, "http://auth", routes["/api/v1/auth"])
	assert.Equal(t, "http://auth", routes["/api/v1/settings"])
	assert.Equal(t, "http://file", routes["/api/v1/folders"])
	assert.Equal(t, "http://doc", routes["/api/v1/templates"])
	assert.Equal(t, "http://collab", routes["/socket.io"])
}
