package config

import (
	"reflect"
	"testing"
	"time"
)

func TestLoadEmptyAndInvalidValues(t *testing.T) {
	for _, k := range []string{"PORT", "RATE_LIMIT_RPS", "CB_FAILURE_RATIO", "SHUTDOWN_TIMEOUT_SECONDS", "CORS_ALLOWED_METHODS", "REDIS_HOST", "JWT_SECRET"} {
		t.Setenv(k, "")
	}
	// An empty string is "set": strings are honoured, numbers and slices fall back.
	cfg := Load()
	if cfg.Port != "" {
		t.Errorf("Port = %q, want explicit empty value to be honoured", cfg.Port)
	}
	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want fallback 100 for unparsable value", cfg.RateLimitRPS)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want fallback 0.6", cfg.CBFailureRatio)
	}
	if cfg.ShutdownTimeout != 30*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 30s", cfg.ShutdownTimeout)
	}
	if len(cfg.CORSAllowedMethods) != 6 {
		t.Errorf("CORSAllowedMethods = %v, want default list for empty value", cfg.CORSAllowedMethods)
	}
}

func TestLoadOverrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CB_MAX_REQUESTS", "7")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")

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
	if cfg.CBMaxRequests != 7 {
		t.Errorf("CBMaxRequests = %d, want 7", cfg.CBMaxRequests)
	}
	if cfg.ShutdownTimeout != 5*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 5s", cfg.ShutdownTimeout)
	}
	want := []string{"https://a.example", "https://b.example"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, want) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, want)
	}
}

func TestGetEnvIntFallbackOnInvalid(t *testing.T) {
	t.Setenv("CFG_TEST_INT", "not-a-number")
	if got := getEnvInt("CFG_TEST_INT", 42); got != 42 {
		t.Errorf("getEnvInt = %d, want 42", got)
	}
	if got := getEnvInt("CFG_TEST_INT_UNSET", 7); got != 7 {
		t.Errorf("getEnvInt unset = %d, want 7", got)
	}
}

func TestGetEnvFloatFallbackOnInvalid(t *testing.T) {
	t.Setenv("CFG_TEST_FLOAT", "abc")
	if got := getEnvFloat("CFG_TEST_FLOAT", 1.5); got != 1.5 {
		t.Errorf("getEnvFloat = %v, want 1.5", got)
	}
}

func TestValidate(t *testing.T) {
	if err := (&Config{}).Validate(); err == nil {
		t.Error("Validate() with empty JWTSecret: want error, got nil")
	}
	if err := (&Config{JWTSecret: "s3cret"}).Validate(); err != nil {
		t.Errorf("Validate() with JWTSecret set: want nil, got %v", err)
	}
}

func TestRedisAddr(t *testing.T) {
	if got := (&Config{RedisPort: "6379"}).RedisAddr(); got != "" {
		t.Errorf("RedisAddr() with no host = %q, want empty", got)
	}
	if got := (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want redis:6380", got)
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
		if routes[prefix] != want {
			t.Errorf("ServiceRoutes()[%q] = %q, want %q", prefix, routes[prefix], want)
		}
	}
}
