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

func TestLoad_Defaults(t *testing.T) {
	for _, key := range []string{
		"PORT", "LOG_LEVEL", "AUTH_SERVICE_URL", "REDIS_HOST", "REDIS_PORT",
		"RATE_LIMIT_RPS", "JWT_SECRET", "JWT_PEER_SECRET", "CORS_ALLOWED_ORIGINS",
		"CORS_MAX_AGE", "SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS",
		"CB_INTERVAL_SECONDS", "CB_TIMEOUT_SECONDS", "CB_FAILURE_RATIO",
	} {
		unsetEnv(t, key)
	}

	cfg := Load()

	if cfg.Port != "8080" {
		t.Errorf("Port = %q, want 8080", cfg.Port)
	}
	if cfg.LogLevel != "info" {
		t.Errorf("LogLevel = %q, want info", cfg.LogLevel)
	}
	if cfg.AuthServiceURL != "http://auth-service:8081" {
		t.Errorf("AuthServiceURL = %q", cfg.AuthServiceURL)
	}
	if cfg.RedisHost != "" || cfg.RedisPort != "6379" {
		t.Errorf("Redis = %q:%q, want empty host and port 6379", cfg.RedisHost, cfg.RedisPort)
	}
	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want 100", cfg.RateLimitRPS)
	}
	if cfg.JWTSecret != "" || cfg.JWTPeerSecret != "" {
		t.Errorf("JWT secrets should default to empty")
	}
	wantOrigins := []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, wantOrigins) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, wantOrigins)
	}
	if cfg.CORSMaxAge != 300 {
		t.Errorf("CORSMaxAge = %d, want 300", cfg.CORSMaxAge)
	}
	if cfg.ShutdownTimeout != 30*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 30s", cfg.ShutdownTimeout)
	}
	if cfg.CBMaxRequests != 5 || cfg.CBInterval != 60*time.Second || cfg.CBTimeout != 30*time.Second || cfg.CBFailureRatio != 0.6 {
		t.Errorf("circuit breaker defaults = %d/%v/%v/%v", cfg.CBMaxRequests, cfg.CBInterval, cfg.CBTimeout, cfg.CBFailureRatio)
	}
}

func TestLoad_Overrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("AUTH_SERVICE_URL", "http://auth.local:1234")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_MAX_REQUESTS", "3")
	t.Setenv("CB_FAILURE_RATIO", "0.25")

	cfg := Load()

	if cfg.Port != "9090" {
		t.Errorf("Port = %q, want 9090", cfg.Port)
	}
	if cfg.AuthServiceURL != "http://auth.local:1234" {
		t.Errorf("AuthServiceURL = %q", cfg.AuthServiceURL)
	}
	if cfg.RateLimitRPS != 7 {
		t.Errorf("RateLimitRPS = %d, want 7", cfg.RateLimitRPS)
	}
	if want := []string{"https://a.example", "https://b.example"}; !reflect.DeepEqual(cfg.CORSAllowedOrigins, want) {
		t.Errorf("CORSAllowedOrigins = %v, want %v", cfg.CORSAllowedOrigins, want)
	}
	if cfg.ShutdownTimeout != 5*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 5s", cfg.ShutdownTimeout)
	}
	if cfg.CBMaxRequests != 3 {
		t.Errorf("CBMaxRequests = %d, want 3", cfg.CBMaxRequests)
	}
	if cfg.CBFailureRatio != 0.25 {
		t.Errorf("CBFailureRatio = %v, want 0.25", cfg.CBFailureRatio)
	}
}

func TestLoad_InvalidNumbersFallBackToDefaults(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CORS_MAX_AGE", "1.5")
	t.Setenv("CB_FAILURE_RATIO", "high")

	cfg := Load()

	if cfg.RateLimitRPS != 100 {
		t.Errorf("RateLimitRPS = %d, want fallback 100", cfg.RateLimitRPS)
	}
	if cfg.CORSMaxAge != 300 {
		t.Errorf("CORSMaxAge = %d, want fallback 300", cfg.CORSMaxAge)
	}
	if cfg.CBFailureRatio != 0.6 {
		t.Errorf("CBFailureRatio = %v, want fallback 0.6", cfg.CBFailureRatio)
	}
}

func TestGetEnv_SetButEmptyIsRespected(t *testing.T) {
	t.Setenv("LOG_LEVEL", "")
	if got := getEnv("LOG_LEVEL", "info"); got != "" {
		t.Errorf("getEnv with empty value = %q, want empty", got)
	}
}

func TestGetEnvSlice_EmptyUsesFallback(t *testing.T) {
	t.Setenv("CORS_ALLOWED_METHODS", "")
	fallback := []string{"GET"}
	if got := getEnvSlice("CORS_ALLOWED_METHODS", fallback); !reflect.DeepEqual(got, fallback) {
		t.Errorf("getEnvSlice with empty value = %v, want %v", got, fallback)
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

func TestRedisAddr(t *testing.T) {
	if got := (&Config{RedisPort: "6379"}).RedisAddr(); got != "" {
		t.Errorf("RedisAddr() with no host = %q, want empty", got)
	}
	if got := (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want redis:6380", got)
	}
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:         "auth",
		FileServiceURL:         "file",
		DocumentServiceURL:     "doc",
		CollabServiceURL:       "collab",
		NotificationServiceURL: "notif",
		SearchServiceURL:       "search",
		AnalyticsServiceURL:    "analytics",
		AdminServiceURL:        "admin",
		AuditServiceURL:        "audit",
		ReportServiceURL:       "report",
	}
	want := map[string]string{
		"/api/v1/auth":          "auth",
		"/api/v1/files":         "file",
		"/api/v1/folders":       "file",
		"/api/v1/documents":     "doc",
		"/api/v1/templates":     "doc",
		"/api/v1/collab":        "collab",
		"/socket.io":            "collab",
		"/api/v1/notifications": "notif",
		"/api/v1/preferences":   "notif",
		"/api/v1/search":        "search",
		"/api/v1/analytics":     "analytics",
		"/api/v1/admin":         "admin",
		"/api/v1/audit":         "audit",
		"/api/v1/reports":       "report",
		"/api/v1/settings":      "auth",
	}
	if got := cfg.ServiceRoutes(); !reflect.DeepEqual(got, want) {
		t.Errorf("ServiceRoutes() = %v, want %v", got, want)
	}
}
