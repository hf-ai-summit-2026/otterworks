package config

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoad_Defaults(t *testing.T) {
	for _, k := range []string{"PORT", "RATE_LIMIT_RPS", "CB_FAILURE_RATIO", "CORS_ALLOWED_ORIGINS", "SHUTDOWN_TIMEOUT_SECONDS", "REDIS_HOST", "JWT_SECRET"} {
		t.Setenv(k, "")
	}
	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS, "empty int env falls back to default")
	assert.Equal(t, 0.6, cfg.CBFailureRatio, "empty float env falls back to default")
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins, "empty slice env falls back to default")
	assert.Equal(t, "", cfg.Port, "string env set to empty is honoured as empty")
}

func TestLoad_Overrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CB_TIMEOUT_SECONDS", "5")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")

	cfg := Load()

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, 250, cfg.RateLimitRPS)
	assert.Equal(t, 0.25, cfg.CBFailureRatio)
	assert.Equal(t, 5*time.Second, cfg.CBTimeout)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
}

func TestLoad_InvalidNumbersFallBack(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CB_FAILURE_RATIO", "abc")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
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
	cfg := &Config{AuthServiceURL: "http://auth", FileServiceURL: "http://file"}
	routes := cfg.ServiceRoutes()

	assert.Equal(t, "http://auth", routes["/api/v1/auth"])
	assert.Equal(t, "http://auth", routes["/api/v1/settings"])
	assert.Equal(t, "http://file", routes["/api/v1/files"])
	assert.Equal(t, "http://file", routes["/api/v1/folders"])
}
