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

func TestRedisAddr(t *testing.T) {
	if got := (&Config{RedisPort: "6379"}).RedisAddr(); got != "" {
		t.Fatalf("expected empty addr when host unset, got %q", got)
	}
	if got := (&Config{RedisHost: "redis", RedisPort: "6380"}).RedisAddr(); got != "redis:6380" {
		t.Fatalf("got %q, want redis:6380", got)
	}
}

func TestGetEnvInt(t *testing.T) {
	t.Setenv("TEST_INT", "42")
	if got := getEnvInt("TEST_INT", 7); got != 42 {
		t.Fatalf("got %d, want 42", got)
	}
	t.Setenv("TEST_INT", "not-a-number")
	if got := getEnvInt("TEST_INT", 7); got != 7 {
		t.Fatalf("invalid value: got %d, want fallback 7", got)
	}
	if got := getEnvInt("TEST_INT_UNSET", 7); got != 7 {
		t.Fatalf("unset: got %d, want fallback 7", got)
	}
}

func TestGetEnvFloat(t *testing.T) {
	t.Setenv("TEST_FLOAT", "0.25")
	if got := getEnvFloat("TEST_FLOAT", 0.6); got != 0.25 {
		t.Fatalf("got %v, want 0.25", got)
	}
	t.Setenv("TEST_FLOAT", "abc")
	if got := getEnvFloat("TEST_FLOAT", 0.6); got != 0.6 {
		t.Fatalf("invalid value: got %v, want fallback 0.6", got)
	}
}

func TestGetEnvSlice(t *testing.T) {
	fallback := []string{"x"}
	t.Setenv("TEST_SLICE", "a,b,c")
	if got := getEnvSlice("TEST_SLICE", fallback); !reflect.DeepEqual(got, []string{"a", "b", "c"}) {
		t.Fatalf("got %v", got)
	}
	t.Setenv("TEST_SLICE", "")
	if got := getEnvSlice("TEST_SLICE", fallback); !reflect.DeepEqual(got, fallback) {
		t.Fatalf("empty value: got %v, want fallback", got)
	}
}

func TestGetEnvEmptyStringOverridesFallback(t *testing.T) {
	t.Setenv("TEST_STR", "")
	if got := getEnv("TEST_STR", "fallback"); got != "" {
		t.Fatalf("got %q, want empty string", got)
	}
}

func TestLoadDefaultsAndOverrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("CB_TIMEOUT_SECONDS", "5")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "bogus")
	t.Setenv("JWT_SECRET", "s3cret")

	cfg := Load()
	if cfg.Port != "9090" {
		t.Errorf("Port = %q, want 9090", cfg.Port)
	}
	if cfg.CBTimeout != 5*time.Second {
		t.Errorf("CBTimeout = %v, want 5s", cfg.CBTimeout)
	}
	if cfg.ShutdownTimeout != 30*time.Second {
		t.Errorf("ShutdownTimeout = %v, want default 30s", cfg.ShutdownTimeout)
	}
	if err := cfg.Validate(); err != nil {
		t.Errorf("Validate() = %v, want nil", err)
	}
}

func TestServiceRoutesTargets(t *testing.T) {
	cfg := &Config{
		AuthServiceURL: "http://auth",
		FileServiceURL: "http://file",
	}
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
