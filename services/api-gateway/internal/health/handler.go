package health

import (
	"encoding/json"
	"net/http"
)

const version = "0.1.0"

// Response represents the health check response payload.
type Response struct {
	Status  string `json:"status"`
	Version string `json:"version"`
}

// Handler returns an HTTP handler that responds with the service health status.
func Handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(Response{
			Status:  "healthy",
			Version: version,
		})
	}
}
