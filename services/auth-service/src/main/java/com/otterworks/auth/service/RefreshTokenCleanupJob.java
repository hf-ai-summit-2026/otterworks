package com.otterworks.auth.service;

import com.otterworks.auth.repository.RefreshTokenRepository;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** Every login and refresh inserts a row; purge expired ones so the table tracks live tokens. */
@Component
public class RefreshTokenCleanupJob {

  private static final Logger log = LoggerFactory.getLogger(RefreshTokenCleanupJob.class);

  private final RefreshTokenRepository refreshTokenRepository;

  public RefreshTokenCleanupJob(RefreshTokenRepository refreshTokenRepository) {
    this.refreshTokenRepository = refreshTokenRepository;
  }

  @Scheduled(
      initialDelayString = "${auth.refresh-token-cleanup.initial-delay:PT10M}",
      fixedDelayString = "${auth.refresh-token-cleanup.interval:PT1H}")
  @Transactional
  public void purgeExpired() {
    int deleted = refreshTokenRepository.deleteExpiredTokens(Instant.now());
    if (deleted > 0) {
      log.info("Purged expired refresh tokens: count={}", deleted);
    }
  }
}
