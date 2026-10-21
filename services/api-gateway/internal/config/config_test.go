package config

import (
	"os"
	"reflect"
	"testing"
	"time"
)

// unsetEnv clears key for the duration of the test and restores it afterwards.
func unsetEnv(t *testing.T, key string) {
	t.Helper()
	t.Setenv(key, "")
	os.Unsetenv(key)
}

func TestLoadDefaults(t *testing.T) {
	for _, k := range []string{
		"PORT", "REDIS_HOST", "REDIS_PORT", "RATE_LIMIT_RPS", "JWT_SECRET",
		"CORS_ALLOWED_ORIGINS", "SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_FAILURE_RATIO",
	} {
		unsetEnv(t, k)
	}

	cfg := Load()

	if cfg.Port != "8080" {
		t.Errorf("Port = %q, want 8080", cfg.Port)
	}
	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want 100", cfg.RateLimitRPS)
	}
	if cfg.ShutdownTimeout != 30*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 30s", cfg.ShutdownTimeout)
	}
	if cfg.CBMaxRequests != 5 {
		t.Errorf("CBMaxRequests = %d, want 5", cfg.CBMaxRequests)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want 0.6", cfg.CBFailureRatio)
	}
	if len(cfg.CORSAllowedOrigins) == 0 {
		t.Error("CORSAllowedOrigins should have defaults")
	}
	if cfg.RedisAddr() != "" {
		t.Errorf("RedisAddr() = %q, want empty when REDIS_HOST unset", cfg.RedisAddr())
	}
	if err := cfg.Validate(); err == nil {
		t.Error("Validate() should fail when JWT_SECRET is unset")
	}
}

func TestLoadFromEnv(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("REDIS_HOST", "redis")
	t.Setenv("REDIS_PORT", "6380")
	t.Setenv("JWT_SECRET", "s3cret")

	cfg := Load()

	if cfg.Port != "9090" {
		t.Errorf("Port = %q, want 9090", cfg.Port)
	}
	if cfg.RateLimitRPS != 250 {
		t.Errorf("RateLimitRPS = %d, want 250", cfg.RateLimitRPS)
	}
	if cfg.ShutdownTimeout != 5*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 5s", cfg.ShutdownTimeout)
	}
	if cfg.CBFailureRatio != 0.25 {
		t.Errorf("CBFailureRatio = %v, want 0.25", cfg.CBFailureRatio)
	}
	want := []string{"https://a.example", "https://b.example"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, want) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, want)
	}
	if got := cfg.RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want redis:6380", got)
	}
	if err := cfg.Validate(); err != nil {
		t.Errorf("Validate() = %v, want nil", err)
	}
}

func TestLoadInvalidNumbersFallBack(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CB_FAILURE_RATIO", "abc")

	cfg := Load()

	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want fallback 100", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want fallback 0.6", cfg.CBFailureRatio)
	}
}

func TestEmptySliceEnvFallsBack(t *testing.T) {
	t.Setenv("CORS_ALLOWED_METHODS", "")

	got := getEnvSlice("CORS_ALLOWED_METHODS", []string{"GET"})
	if !reflect.DeepEqual(got, []string{"GET"}) {
		t.Errorf("getEnvSlice = %v, want fallback [GET]", got)
	}
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL: "http://auth",
		FileServiceURL: "http://file",
	}
	routes := cfg.ServiceRoutes()

	cases := map[string]string{
		"/api/v1/auth":     "http://auth",
		"/api/v1/settings": "http://auth",
		"/api/v1/files":    "http://file",
		"/api/v1/folders":  "http://file",
	}
	for prefix, want := range cases {
		if got := routes[prefix]; got != want {
			t.Errorf("routes[%q] = %q, want %q", prefix, got, want)
		}
	}
	if len(routes) != 15 {
		t.Errorf("len(routes) = %d, want 15", len(routes))
	}
}
