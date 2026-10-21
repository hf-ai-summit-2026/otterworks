package com.otterworks.auth.repository;

import com.otterworks.auth.entity.User;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface UserRepository extends JpaRepository<User, UUID> {
  Optional<User> findByEmail(String email);

  boolean existsByEmail(String email);

  @Modifying
  @Query("UPDATE User u SET u.lastLoginAt = :at, u.updatedAt = :at WHERE u.id = :id")
  int updateLastLoginAt(@Param("id") UUID id, @Param("at") Instant at);
}
