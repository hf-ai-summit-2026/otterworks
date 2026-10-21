package com.otterworks.auth.service;

import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
import com.otterworks.auth.dto.LoginRequest;
import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionOperations;

@Service
public class AuthService {

  private static final Logger log = LoggerFactory.getLogger(AuthService.class);

  private final UserRepository userRepository;
  private final PasswordEncoder passwordEncoder;
  private final JwtTokenProvider jwtTokenProvider;
  private final RefreshTokenRepository refreshTokenRepository;
  private final TransactionOperations transactionOperations;

  public AuthService(
      UserRepository userRepository,
      PasswordEncoder passwordEncoder,
      JwtTokenProvider jwtTokenProvider,
      RefreshTokenRepository refreshTokenRepository,
      TransactionOperations transactionOperations) {
    this.userRepository = userRepository;
    this.passwordEncoder = passwordEncoder;
    this.jwtTokenProvider = jwtTokenProvider;
    this.refreshTokenRepository = refreshTokenRepository;
    this.transactionOperations = transactionOperations;
  }

  // BCrypt hashing (~250ms of CPU at cost 12) deliberately runs outside any transaction so a
  // login or registration only holds a database connection for its short writes.
  public AuthResponse register(RegisterRequest request) {
    if (userRepository.existsByEmail(request.getEmail())) {
      throw new IllegalArgumentException("Email already registered");
    }

    String passwordHash = passwordEncoder.encode(request.getPassword());

    return transactionOperations.execute(
        status -> {
          User user = new User();
          user.setEmail(request.getEmail());
          user.setPasswordHash(passwordHash);
          user.setDisplayName(request.getDisplayName());
          user.setRoles(Set.of(User.Role.USER));
          user = userRepository.save(user);

          log.info("User registered: email={}", user.getEmail());
          return buildAuthResponse(user);
        });
  }

  public AuthResponse login(LoginRequest request) {
    User user =
        userRepository
            .findByEmail(request.getEmail())
            .orElseThrow(() -> new IllegalArgumentException("Invalid credentials"));

    if (!passwordEncoder.matches(request.getPassword(), user.getPasswordHash())) {
      throw new IllegalArgumentException("Invalid credentials");
    }

    AuthResponse response =
        transactionOperations.execute(
            status -> {
              Instant now = Instant.now();
              userRepository.updateLastLoginAt(user.getId(), now);
              user.setLastLoginAt(now);
              return buildAuthResponse(user);
            });

    log.info("User logged in: email={}", user.getEmail());
    return response;
  }

  @Transactional
  public AuthResponse refreshToken(String token) {
    String jti = jwtTokenProvider.extractJti(token);
    String userId = jwtTokenProvider.validateRefreshTokenAndGetUserId(token);

    RefreshToken storedToken =
        refreshTokenRepository
            .findByTokenIdAndRevokedFalse(jti)
            .orElseThrow(() -> new IllegalArgumentException("Invalid or revoked refresh token"));

    if (storedToken.getExpiresAt().isBefore(Instant.now())) {
      throw new IllegalArgumentException("Refresh token expired");
    }

    storedToken.setRevoked(true);
    refreshTokenRepository.save(storedToken);

    User user =
        userRepository
            .findById(UUID.fromString(userId))
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    log.info("Token refreshed for user: {}", user.getEmail());
    return buildAuthResponse(user);
  }

  public void changePassword(UUID userId, ChangePasswordRequest request) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    if (!passwordEncoder.matches(request.getCurrentPassword(), user.getPasswordHash())) {
      throw new IllegalArgumentException("Current password is incorrect");
    }

    String newPasswordHash = passwordEncoder.encode(request.getNewPassword());

    transactionOperations.executeWithoutResult(
        status -> {
          user.setPasswordHash(newPasswordHash);
          userRepository.save(user);
          refreshTokenRepository.revokeAllByUserId(userId);
        });
    log.info("Password changed for user: {}", userId);
  }

  @Transactional
  public void logout(UUID userId) {
    refreshTokenRepository.revokeAllByUserId(userId);
    log.info("User logged out: {}", userId);
  }

  private AuthResponse buildAuthResponse(User user) {
    String accessToken = jwtTokenProvider.generateAccessToken(user);
    String refreshTokenStr = jwtTokenProvider.generateRefreshToken(user);

    String jti = jwtTokenProvider.extractJti(refreshTokenStr);
    RefreshToken refreshToken = new RefreshToken();
    refreshToken.setUser(user);
    refreshToken.setTokenId(jti);
    refreshToken.setExpiresAt(
        Instant.now().plus(jwtTokenProvider.getRefreshTokenExpiry(), ChronoUnit.SECONDS));
    refreshTokenRepository.save(refreshToken);

    return new AuthResponse(
        accessToken,
        refreshTokenStr,
        "Bearer",
        jwtTokenProvider.getAccessTokenExpiry(),
        new AuthResponse.UserDto(
            user.getId().toString(), user.getEmail(), user.getDisplayName(), user.getAvatarUrl()));
  }
}
