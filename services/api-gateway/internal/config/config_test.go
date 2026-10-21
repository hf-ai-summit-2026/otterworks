package config

import (
	"os"
	"reflect"
	"testing"
	"time"
)

func TestLoadDefaults(t *testing.T) {
	unsetForTest(t, "PORT", "AUTH_SERVICE_URL", "REDIS_PORT", "RATE_LIMIT_RPS",
		"SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_FAILURE_RATIO")
	// An empty CORS_ALLOWED_ORIGINS falls back to the defaults.
	t.Setenv("CORS_ALLOWED_ORIGINS", "")

	cfg := Load()

	if cfg.Port != "8080" {
		t.Errorf("Port = %q, want 8080", cfg.Port)
	}
	if cfg.AuthServiceURL != "http://auth-service:8081" {
		t.Errorf("AuthServiceURL = %q", cfg.AuthServiceURL)
	}
	if cfg.RedisPort != "6379" {
		t.Errorf("RedisPort = %q, want 6379", cfg.RedisPort)
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
	wantOrigins := []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, wantOrigins) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, wantOrigins)
	}
}

func TestLoadOverrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("RATE_LIMIT_RPS", "250")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CB_INTERVAL_SECONDS", "10")
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
	if cfg.CBInterval != 10*time.Second {
		t.Errorf("CBInterval = %v, want 10s", cfg.CBInterval)
	}
	want := []string{"https://a.example", "https://b.example"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, want) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, want)
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

func TestValidate(t *testing.T) {
	if err := (&Config{}).Validate(); err == nil {
		t.Error("Validate() with empty JWTSecret returned nil, want error")
	}
	if err := (&Config{JWTSecret: "s3cret"}).Validate(); err != nil {
		t.Errorf("Validate() with JWTSecret set returned %v, want nil", err)
	}
}

func TestRedisAddr(t *testing.T) {
	if got := (&Config{RedisPort: "6379"}).RedisAddr(); got != "" {
		t.Errorf("RedisAddr() with empty host = %q, want empty", got)
	}
	if got := (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want redis:6380", got)
	}
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:         "http://auth",
		FileServiceURL:         "http://file",
		DocumentServiceURL:     "http://doc",
		CollabServiceURL:       "http://collab",
		NotificationServiceURL: "http://notif",
		SearchServiceURL:       "http://search",
		AnalyticsServiceURL:    "http://analytics",
		AdminServiceURL:        "http://admin",
		AuditServiceURL:        "http://audit",
		ReportServiceURL:       "http://report",
	}

	routes := cfg.ServiceRoutes()

	cases := map[string]string{
		"/api/v1/auth":      "http://auth",
		"/api/v1/settings":  "http://auth",
		"/api/v1/folders":   "http://file",
		"/api/v1/templates": "http://doc",
		"/socket.io":        "http://collab",
		"/api/v1/reports":   "http://report",
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

// unsetForTest removes env vars for the duration of the test, restoring them afterwards.
func unsetForTest(t *testing.T, keys ...string) {
	t.Helper()
	for _, k := range keys {
		t.Setenv(k, "")
		if err := os.Unsetenv(k); err != nil {
			t.Fatalf("unset %s: %v", k, err)
		}
	}
}
