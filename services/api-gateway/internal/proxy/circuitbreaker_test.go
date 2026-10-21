package proxy

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func defaultTestConfig() CircuitBreakerConfig {
	return CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      10 * time.Second,
		FailureRatio: 0.5,
	}
}

func TestCircuitBreaker_StartsInClosedState(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", defaultTestConfig())
	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_SuccessfulRequests(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", defaultTestConfig())

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	for i := 0; i < 10; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		err := cb.Execute(handler, rec, req)
		require.NoError(t, err)
		assert.Equal(t, http.StatusOK, rec.Code)
	}

	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_TripsOnFailures(t *testing.T) {
	cfg := CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      10 * time.Second,
		FailureRatio: 0.5,
	}
	cb := NewCircuitBreaker("test-svc", cfg)

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	// Send enough requests to trip the breaker (need at least 5 total, >50% failures)
	for i := 0; i < 6; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		_ = cb.Execute(failHandler, rec, req)
	}

	assert.Equal(t, StateOpen, cb.State())

	// Next request should be rejected
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	err := cb.Execute(failHandler, rec, req)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "circuit breaker test-svc is open")
}

func TestCircuitBreaker_TransitionsToHalfOpen(t *testing.T) {
	cfg := CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      5 * time.Second,
		FailureRatio: 0.5,
	}
	cb := NewCircuitBreaker("test-svc", cfg)

	now := time.Now()
	cb.now = func() time.Time { return now }

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	// Trip the breaker
	for i := 0; i < 6; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		_ = cb.Execute(failHandler, rec, req)
	}
	assert.Equal(t, StateOpen, cb.State())

	// Advance time past timeout
	cb.now = func() time.Time { return now.Add(6 * time.Second) }
	assert.Equal(t, StateHalfOpen, cb.State())
}

func TestCircuitBreaker_RecoveryFromHalfOpen(t *testing.T) {
	cfg := CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      5 * time.Second,
		FailureRatio: 0.5,
	}
	cb := NewCircuitBreaker("test-svc", cfg)

	now := time.Now()
	cb.now = func() time.Time { return now }

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	successHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	// Trip the breaker
	for i := 0; i < 6; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		_ = cb.Execute(failHandler, rec, req)
	}
	assert.Equal(t, StateOpen, cb.State())

	// Advance time to half-open
	cb.now = func() time.Time { return now.Add(6 * time.Second) }

	// Successful requests in half-open should close the breaker
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		err := cb.Execute(successHandler, rec, req)
		require.NoError(t, err)
	}

	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreakerManager_GetOrCreate(t *testing.T) {
	mgr := NewCircuitBreakerManager(defaultTestConfig())

	cb1 := mgr.Get("service-a")
	cb2 := mgr.Get("service-a")
	cb3 := mgr.Get("service-b")

	assert.Same(t, cb1, cb2, "same name should return same instance")
	assert.NotSame(t, cb1, cb3, "different names should return different instances")
}

func TestCircuitState_String(t *testing.T) {
	assert.Equal(t, "closed", StateClosed.String())
	assert.Equal(t, "open", StateOpen.String())
	assert.Equal(t, "half-open", StateHalfOpen.String())
}
