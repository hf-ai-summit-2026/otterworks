package config

import (
	"os"
	"reflect"
	"testing"
	"time"
)

func TestLoadDefaults(t *testing.T) {
	unsetEnv(t, "PORT", "RATE_LIMIT_RPS", "CORS_ALLOWED_ORIGINS", "SHUTDOWN_TIMEOUT_SECONDS", "CB_FAILURE_RATIO", "REDIS_HOST")
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
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want 0.6", cfg.CBFailureRatio)
	}
	if len(cfg.CORSAllowedOrigins) == 0 {
		t.Error("CORSAllowedOrigins should have defaults")
	}
	if cfg.RedisAddr() != "" {
		t.Errorf("RedisAddr() = %q, want empty when REDIS_HOST unset", cfg.RedisAddr())
	}
}

func TestLoadOverrides(t *testing.T) {
	t.Setenv("PORT", "9000")
	t.Setenv("RATE_LIMIT_RPS", "25")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("REDIS_HOST", "redis")
	t.Setenv("REDIS_PORT", "6380")

	cfg := Load()

	if cfg.Port != "9000" {
		t.Errorf("Port = %q, want 9000", cfg.Port)
	}
	if cfg.RateLimitRPS != 25 {
		t.Errorf("RateLimitRPS = %d, want 25", cfg.RateLimitRPS)
	}
	want := []string{"https://a.example", "https://b.example"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, want) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, want)
	}
	if cfg.ShutdownTimeout != 5*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 5s", cfg.ShutdownTimeout)
	}
	if cfg.CBFailureRatio != 0.25 {
		t.Errorf("CBFailureRatio = %v, want 0.25", cfg.CBFailureRatio)
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
		t.Errorf("RateLimitRPS = %d, want fallback 100", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want fallback 0.6", cfg.CBFailureRatio)
	}
}

func TestGetEnvSliceEmptyUsesFallback(t *testing.T) {
	t.Setenv("CORS_ALLOWED_METHODS", "")
	got := getEnvSlice("CORS_ALLOWED_METHODS", []string{"GET"})
	if !reflect.DeepEqual(got, []string{"GET"}) {
		t.Errorf("getEnvSlice with empty value = %v, want [GET]", got)
	}
}

func TestValidate(t *testing.T) {
	if err := (&Config{}).Validate(); err == nil {
		t.Error("Validate() with empty JWTSecret should return an error")
	}
	if err := (&Config{JWTSecret: "s3cret"}).Validate(); err != nil {
		t.Errorf("Validate() with JWTSecret set returned %v", err)
	}
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:     "http://auth",
		FileServiceURL:     "http://file",
		DocumentServiceURL: "http://doc",
		CollabServiceURL:   "http://collab",
	}
	routes := cfg.ServiceRoutes()

	cases := map[string]string{
		"/api/v1/auth":      "http://auth",
		"/api/v1/settings":  "http://auth",
		"/api/v1/files":     "http://file",
		"/api/v1/folders":   "http://file",
		"/api/v1/documents": "http://doc",
		"/api/v1/templates": "http://doc",
		"/socket.io":        "http://collab",
	}
	for prefix, want := range cases {
		if got := routes[prefix]; got != want {
			t.Errorf("routes[%q] = %q, want %q", prefix, got, want)
		}
	}
}

// unsetEnv clears keys for the duration of the test, restoring them afterwards.
func unsetEnv(t *testing.T, keys ...string) {
	t.Helper()
	for _, k := range keys {
		t.Setenv(k, "")
		os.Unsetenv(k)
	}
}
