package config

import (
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

func TestLoadDefaults(t *testing.T) {
	for _, k := range []string{
		"PORT", "RATE_LIMIT_RPS", "CB_FAILURE_RATIO", "CB_MAX_REQUESTS",
		"SHUTDOWN_TIMEOUT_SECONDS", "CORS_ALLOWED_ORIGINS", "REDIS_HOST", "JWT_SECRET",
	} {
		t.Setenv(k, "")
	}
	// Empty values fall back to defaults for numeric and slice settings.
	cfg := Load()
	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want 100", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want 0.6", cfg.CBFailureRatio)
	}
	if cfg.CBMaxRequests != 5 {
		t.Errorf("CBMaxRequests = %d, want 5", cfg.CBMaxRequests)
	}
	if cfg.ShutdownTimeout != 30*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 30s", cfg.ShutdownTimeout)
	}
	if len(cfg.CORSAllowedOrigins) != 4 {
		t.Errorf("CORSAllowedOrigins = %v, want 4 defaults", cfg.CORSAllowedOrigins)
	}
	if cfg.RedisAddr() != "" {
		t.Errorf("RedisAddr() = %q, want empty when REDIS_HOST is empty", cfg.RedisAddr())
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
	t.Setenv("JWT_SECRET", "abc")

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
	t.Setenv("CB_INTERVAL_SECONDS", "1.5")

	cfg := Load()
	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want fallback 100", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want fallback 0.6", cfg.CBFailureRatio)
	}
	if cfg.CBInterval != 60*time.Second {
		t.Errorf("CBInterval = %v, want fallback 60s", cfg.CBInterval)
	}
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{AuthServiceURL: "http://auth", FileServiceURL: "http://file"}
	routes := cfg.ServiceRoutes()
	for prefix, want := range map[string]string{
		"/api/v1/auth":     "http://auth",
		"/api/v1/settings": "http://auth",
		"/api/v1/files":    "http://file",
		"/api/v1/folders":  "http://file",
	} {
		if got := routes[prefix]; got != want {
			t.Errorf("routes[%q] = %q, want %q", prefix, got, want)
		}
	}
}
