package config

import (
	"reflect"
	"testing"
	"time"
)

func TestLoadDefaults(t *testing.T) {
	for _, k := range []string{
		"RATE_LIMIT_RPS", "CORS_ALLOWED_ORIGINS",
		"SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_FAILURE_RATIO",
	} {
		t.Setenv(k, "")
	}
	// Empty numeric and list variables fall back to their defaults.
	cfg := Load()

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
	if len(cfg.CORSAllowedOrigins) != 4 {
		t.Errorf("CORSAllowedOrigins = %v, want 4 defaults", cfg.CORSAllowedOrigins)
	}
}

func TestLoadFromEnv(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
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
	if cfg.JWTSecret != "s3cret" {
		t.Errorf("JWTSecret not loaded from env")
	}
}

func TestGetEnvInvalidNumbersFallBack(t *testing.T) {
	t.Setenv("TEST_CFG_INT", "not-a-number")
	t.Setenv("TEST_CFG_FLOAT", "abc")

	if got := getEnvInt("TEST_CFG_INT", 42); got != 42 {
		t.Errorf("getEnvInt invalid = %d, want fallback 42", got)
	}
	if got := getEnvFloat("TEST_CFG_FLOAT", 1.5); got != 1.5 {
		t.Errorf("getEnvFloat invalid = %v, want fallback 1.5", got)
	}
	if got := getEnvInt("TEST_CFG_UNSET_INT", 7); got != 7 {
		t.Errorf("getEnvInt unset = %d, want fallback 7", got)
	}
}

func TestGetEnvEmptyValue(t *testing.T) {
	t.Setenv("TEST_CFG_STR", "")
	t.Setenv("TEST_CFG_SLICE", "")

	// An explicitly empty string is honoured by getEnv...
	if got := getEnv("TEST_CFG_STR", "fallback"); got != "" {
		t.Errorf("getEnv empty = %q, want empty", got)
	}
	// ...but an empty slice variable falls back to the defaults.
	if got := getEnvSlice("TEST_CFG_SLICE", []string{"x"}); !reflect.DeepEqual(got, []string{"x"}) {
		t.Errorf("getEnvSlice empty = %v, want [x]", got)
	}
}

func TestValidate(t *testing.T) {
	if err := (&Config{}).Validate(); err == nil {
		t.Error("Validate() with empty JWTSecret = nil, want error")
	}
	if err := (&Config{JWTSecret: "s"}).Validate(); err != nil {
		t.Errorf("Validate() with JWTSecret = %v, want nil", err)
	}
}

func TestRedisAddr(t *testing.T) {
	if got := (&Config{RedisPort: "6379"}).RedisAddr(); got != "" {
		t.Errorf("RedisAddr() without host = %q, want empty", got)
	}
	if got := (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want redis:6380", got)
	}
}

func TestServiceRoutesCoverAllPrefixes(t *testing.T) {
	cfg := &Config{AuthServiceURL: "http://auth", FileServiceURL: "http://file", DocumentServiceURL: "http://doc"}
	routes := cfg.ServiceRoutes()

	cases := map[string]string{
		"/api/v1/auth":      "http://auth",
		"/api/v1/settings":  "http://auth",
		"/api/v1/files":     "http://file",
		"/api/v1/folders":   "http://file",
		"/api/v1/documents": "http://doc",
		"/api/v1/templates": "http://doc",
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
