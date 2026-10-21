package config

import (
	"strings"
	"testing"
)

func validConfig() *Config {
	return &Config{
		JWTSecret:              "secret",
		AuthServiceURL:         "http://auth-service:8081",
		FileServiceURL:         "http://file-service:8082",
		DocumentServiceURL:     "http://document-service:8083",
		CollabServiceURL:       "http://collab-service:8084",
		NotificationServiceURL: "http://notification-service:8086",
		SearchServiceURL:       "http://search-service:8087",
		AnalyticsServiceURL:    "http://analytics-service:8088",
		AdminServiceURL:        "http://admin-service:8089",
		AuditServiceURL:        "https://audit-service:8090",
		ReportServiceURL:       "http://report-service:8091",
	}
}

func TestValidate_AcceptsCompleteConfig(t *testing.T) {
	if err := validConfig().Validate(); err != nil {
		t.Fatalf("expected valid config, got %v", err)
	}
}

func TestValidate_DefaultsFromLoadAreValid(t *testing.T) {
	t.Setenv("JWT_SECRET", "secret")
	if err := Load().Validate(); err != nil {
		t.Fatalf("expected Load() defaults to validate, got %v", err)
	}
}

func TestValidate_RequiresJWTSecret(t *testing.T) {
	cfg := validConfig()
	cfg.JWTSecret = ""
	err := cfg.Validate()
	if err == nil || !strings.Contains(err.Error(), "JWT_SECRET") {
		t.Fatalf("expected JWT_SECRET error, got %v", err)
	}
}

func TestValidate_RequiresEveryBackendURL(t *testing.T) {
	fields := map[string]func(*Config){
		"AUTH_SERVICE_URL":         func(c *Config) { c.AuthServiceURL = "" },
		"FILE_SERVICE_URL":         func(c *Config) { c.FileServiceURL = "" },
		"DOCUMENT_SERVICE_URL":     func(c *Config) { c.DocumentServiceURL = "" },
		"COLLAB_SERVICE_URL":       func(c *Config) { c.CollabServiceURL = "" },
		"NOTIFICATION_SERVICE_URL": func(c *Config) { c.NotificationServiceURL = "" },
		"SEARCH_SERVICE_URL":       func(c *Config) { c.SearchServiceURL = "" },
		"ANALYTICS_SERVICE_URL":    func(c *Config) { c.AnalyticsServiceURL = "" },
		"ADMIN_SERVICE_URL":        func(c *Config) { c.AdminServiceURL = "" },
		"AUDIT_SERVICE_URL":        func(c *Config) { c.AuditServiceURL = "" },
		"REPORT_SERVICE_URL":       func(c *Config) { c.ReportServiceURL = "" },
	}
	for env, clear := range fields {
		t.Run(env, func(t *testing.T) {
			cfg := validConfig()
			clear(cfg)
			err := cfg.Validate()
			if err == nil || !strings.Contains(err.Error(), env) {
				t.Fatalf("expected error mentioning %s, got %v", env, err)
			}
		})
	}
}

func TestValidate_EmptyEnvOverrideFailsFast(t *testing.T) {
	t.Setenv("JWT_SECRET", "secret")
	t.Setenv("SEARCH_SERVICE_URL", "")
	err := Load().Validate()
	if err == nil || !strings.Contains(err.Error(), "SEARCH_SERVICE_URL") {
		t.Fatalf("expected SEARCH_SERVICE_URL error, got %v", err)
	}
}

func TestValidate_RejectsMalformedURLs(t *testing.T) {
	for _, raw := range []string{"search-service:8087", "ftp://search-service", "http://", "://bad"} {
		t.Run(raw, func(t *testing.T) {
			cfg := validConfig()
			cfg.SearchServiceURL = raw
			if err := cfg.Validate(); err == nil {
				t.Fatalf("expected %q to be rejected", raw)
			}
		})
	}
}

func TestValidate_ReportsAllProblems(t *testing.T) {
	cfg := validConfig()
	cfg.JWTSecret = ""
	cfg.AdminServiceURL = ""
	cfg.AuditServiceURL = ""
	msg := cfg.Validate().Error()
	for _, want := range []string{"JWT_SECRET", "ADMIN_SERVICE_URL", "AUDIT_SERVICE_URL"} {
		if !strings.Contains(msg, want) {
			t.Errorf("expected %q in %q", want, msg)
		}
	}
}
