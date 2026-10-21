package config

import (
	"os"
	"reflect"
	"testing"
	"time"
)

func TestValidate(t *testing.T) {
	if err := (&Config{}).Validate(); err == nil {
		t.Fatal("expected error when JWTSecret is empty")
	}
	if err := (&Config{JWTSecret: "s3cret"}).Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func unsetEnv(t *testing.T, key string) {
	t.Helper()
	t.Setenv(key, "") // registers restore of the original value on cleanup
	os.Unsetenv(key)
}

func TestLoadDefaults(t *testing.T) {
	for _, k := range []string{
		"PORT", "RATE_LIMIT_RPS", "JWT_SECRET", "CORS_ALLOWED_METHODS",
		"SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_FAILURE_RATIO", "REDIS_HOST",
	} {
		unsetEnv(t, k)
	}
	cfg := Load()

	if cfg.Port != "8080" {
		t.Errorf("Port = %q, want 8080", cfg.Port)
	}
	if cfg.JWTSecret != "" {
		t.Errorf("JWTSecret = %q, want empty", cfg.JWTSecret)
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
	wantMethods := []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
	if !reflect.DeepEqual(cfg.CORSAllowedMethods, wantMethods) {
		t.Errorf("CORSAllowedMethods = %v, want %v", cfg.CORSAllowedMethods, wantMethods)
	}
	if cfg.RedisAddr() != "" {
		t.Errorf("RedisAddr() = %q, want empty when REDIS_HOST is unset", cfg.RedisAddr())
	}
}

func TestLoadOverrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CB_TIMEOUT_SECONDS", "7")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("REDIS_HOST", "redis")
	t.Setenv("REDIS_PORT", "6380")

	cfg := Load()

	if cfg.Port != "9090" {
		t.Errorf("Port = %q, want 9090", cfg.Port)
	}
	if cfg.RateLimitRPS != 250 {
		t.Errorf("RateLimitRPS = %d, want 250", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.25 {
		t.Errorf("CBFailureRatio = %v, want 0.25", cfg.CBFailureRatio)
	}
	if cfg.CBTimeout != 7*time.Second {
		t.Errorf("CBTimeout = %v, want 7s", cfg.CBTimeout)
	}
	wantOrigins := []string{"https://a.example", "https://b.example"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, wantOrigins) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, wantOrigins)
	}
	if got := cfg.RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want redis:6380", got)
	}
}

func TestLoadInvalidNumbersFallBack(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CB_FAILURE_RATIO", "abc")

	cfg := Load()

	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want default 100", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want default 0.6", cfg.CBFailureRatio)
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
