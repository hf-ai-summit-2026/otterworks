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
	if err := (&Config{JWTSecret: "s"}).Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestRedisAddr(t *testing.T) {
	if got := (&Config{RedisPort: "6379"}).RedisAddr(); got != "" {
		t.Errorf("RedisAddr() with empty host = %q, want empty", got)
	}
	if got := (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr(); got != "redis:6380" {
		t.Errorf("RedisAddr() = %q, want %q", got, "redis:6380")
	}
}

func TestGetEnvInt(t *testing.T) {
	t.Setenv("CFG_TEST_INT", "42")
	if got := getEnvInt("CFG_TEST_INT", 7); got != 42 {
		t.Errorf("getEnvInt valid = %d, want 42", got)
	}
	t.Setenv("CFG_TEST_INT", "not-a-number")
	if got := getEnvInt("CFG_TEST_INT", 7); got != 7 {
		t.Errorf("getEnvInt invalid = %d, want fallback 7", got)
	}
	if got := getEnvInt("CFG_TEST_INT_UNSET", 7); got != 7 {
		t.Errorf("getEnvInt unset = %d, want fallback 7", got)
	}
}

func TestGetEnvFloat(t *testing.T) {
	t.Setenv("CFG_TEST_FLOAT", "0.25")
	if got := getEnvFloat("CFG_TEST_FLOAT", 0.6); got != 0.25 {
		t.Errorf("getEnvFloat valid = %v, want 0.25", got)
	}
	t.Setenv("CFG_TEST_FLOAT", "abc")
	if got := getEnvFloat("CFG_TEST_FLOAT", 0.6); got != 0.6 {
		t.Errorf("getEnvFloat invalid = %v, want fallback 0.6", got)
	}
}

func TestGetEnvSlice(t *testing.T) {
	fallback := []string{"a"}
	t.Setenv("CFG_TEST_SLICE", "x,y,z")
	if got := getEnvSlice("CFG_TEST_SLICE", fallback); !reflect.DeepEqual(got, []string{"x", "y", "z"}) {
		t.Errorf("getEnvSlice = %v, want [x y z]", got)
	}
	t.Setenv("CFG_TEST_SLICE", "")
	if got := getEnvSlice("CFG_TEST_SLICE", fallback); !reflect.DeepEqual(got, fallback) {
		t.Errorf("getEnvSlice empty = %v, want fallback", got)
	}
}

func TestGetEnvEmptyStringOverridesFallback(t *testing.T) {
	t.Setenv("CFG_TEST_STR", "")
	if got := getEnv("CFG_TEST_STR", "default"); got != "" {
		t.Errorf("getEnv set-but-empty = %q, want empty", got)
	}
	if got := getEnv("CFG_TEST_STR_UNSET", "default"); got != "default" {
		t.Errorf("getEnv unset = %q, want default", got)
	}
}

func TestLoadOverrides(t *testing.T) {
	t.Setenv("PORT", "9999")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_MAX_REQUESTS", "3")
	t.Setenv("JWT_SECRET", "secret")

	cfg := Load()
	if cfg.Port != "9999" {
		t.Errorf("Port = %q, want 9999", cfg.Port)
	}
	if cfg.ShutdownTimeout != 5*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 5s", cfg.ShutdownTimeout)
	}
	if cfg.CBMaxRequests != 3 {
		t.Errorf("CBMaxRequests = %d, want 3", cfg.CBMaxRequests)
	}
	if err := cfg.Validate(); err != nil {
		t.Errorf("Validate() = %v, want nil", err)
	}
}

func TestServiceRoutesCoverAllBackends(t *testing.T) {
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
