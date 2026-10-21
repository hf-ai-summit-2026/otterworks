package com.otterworks.auth.repository;

import com.otterworks.auth.entity.RefreshToken;
import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface RefreshTokenRepository extends JpaRepository<RefreshToken, UUID> {
  @Lock(LockModeType.PESSIMISTIC_WRITE)
  Optional<RefreshToken> findByTokenIdAndRevokedFalse(String tokenId);

  @Modifying
  @Query(
      "UPDATE RefreshToken r SET r.revoked = true WHERE r.user.id = :userId AND r.revoked = false")
  void revokeAllByUserId(@Param("userId") UUID userId);

  @Modifying
  @Query("DELETE FROM RefreshToken r WHERE r.expiresAt < :now")
  int deleteExpiredTokens(@Param("now") Instant now);
}
