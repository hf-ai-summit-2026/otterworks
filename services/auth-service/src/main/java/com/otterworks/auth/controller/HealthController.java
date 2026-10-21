package com.otterworks.auth.controller;

import java.util.LinkedHashMap;
import java.util.Map;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

  private static final Logger log = LoggerFactory.getLogger(HealthController.class);

  private final DataSource dataSource;

  public HealthController(DataSource dataSource) {
    this.dataSource = dataSource;
  }

  /** Liveness: process is up. Deliberately DB-free so a slow database never restarts pods. */
  @GetMapping("/livez")
  public ResponseEntity<Map<String, Object>> liveness() {
    return ResponseEntity.ok(Map.of("service", "auth-service", "status", "alive"));
  }

  @GetMapping("/health")
  public ResponseEntity<Map<String, Object>> health() {
    Map<String, Object> response = new LinkedHashMap<>();
    response.put("service", "auth-service");

    boolean dbHealthy = checkDatabaseConnectivity();
    response.put("status", dbHealthy ? "healthy" : "degraded");

    Map<String, Object> dbStatus = new LinkedHashMap<>();
    dbStatus.put("status", dbHealthy ? "up" : "down");
    response.put("database", dbStatus);

    HttpStatus status = dbHealthy ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE;
    return ResponseEntity.status(status).body(response);
  }

  private boolean checkDatabaseConnectivity() {
    try (var connection = dataSource.getConnection()) {
      return connection.isValid(3);
    } catch (Exception e) {
      log.warn("Database health check failed: {}", e.getMessage());
      return false;
    }
  }
}
