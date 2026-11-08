package com.fintech.auth.service;

import com.fintech.auth.domain.*;
import com.fintech.auth.dto.*;
import com.fintech.auth.repository.*;
import com.fintech.auth.security.JwtService;
import com.fintech.auth.security.PasswordConfig;
import com.fintech.platform.correlation.CorrelationContext;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.outbox.EventEnvelope;
import com.fintech.platform.outbox.OutboxService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Base64;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    private final UserRepository userRepository;
    private final RefreshTokenRepository refreshTokenRepository;
    private final LoginAttemptRepository loginAttemptRepository;
    private final LoginAttemptService loginAttemptService;
    private final ServiceClientRepository serviceClientRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final OutboxService outboxService;

    @Value("${app.security.lockout.max-failed-attempts:5}")
    private int maxFailedAttempts;

    @Value("${app.security.lockout.window-minutes:15}")
    private int lockoutWindowMinutes;

    @Value("${app.jwt.refresh-token-ttl-seconds:604800}") // 7 days
    private long refreshTokenTtlSeconds;

    public AuthService(
            UserRepository userRepository,
            RefreshTokenRepository refreshTokenRepository,
            LoginAttemptRepository loginAttemptRepository,
            LoginAttemptService loginAttemptService,
            ServiceClientRepository serviceClientRepository,
            PasswordEncoder passwordEncoder,
            JwtService jwtService,
            OutboxService outboxService
    ) {
        this.userRepository = userRepository;
        this.refreshTokenRepository = refreshTokenRepository;
        this.loginAttemptRepository = loginAttemptRepository;
        this.loginAttemptService = loginAttemptService;
        this.serviceClientRepository = serviceClientRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.outboxService = outboxService;
    }

    /**
     * Customer registration.
     * Enforces uniqueness, creates User, and emits UserRegistered event to Outbox in the same transaction.
     */
    @Transactional
    public User registerCustomer(RegisterRequest request) {
        if (userRepository.existsByEmail(request.email())) {
            throw new BusinessException(ErrorCode.EMAIL_ALREADY_EXISTS, "Email is already registered: " + request.email());
        }
        if (userRepository.existsByUsername(request.username())) {
            throw new BusinessException(ErrorCode.USERNAME_TAKEN, "Username is already taken: " + request.username());
        }
        if (userRepository.existsByPhone(request.phone())) {
            throw new BusinessException(ErrorCode.PHONE_ALREADY_EXISTS, "Phone number is already registered: " + request.phone());
        }

        UUID userId = UUID.randomUUID();
        String hashedPassword = passwordEncoder.encode(request.password());

        User user = new User(
                userId,
                request.email(),
                request.username(),
                request.phone(),
                hashedPassword,
                Role.CUSTOMER,
                request.accountKind()
        );

        user = userRepository.save(user);

        // Transactional Outbox: UserRegistered event (consumed by Customer and Transaction services)
        String displayName = (request.displayName() != null && !request.displayName().isBlank()) 
                ? request.displayName() 
                : request.username();

        UserRegisteredEvent eventData = new UserRegisteredEvent(
                user.getId(),
                user.getEmail(),
                user.getUsername(),
                user.getPhone(),
                user.getRole(),
                user.getAccountKind(),
                displayName,
                Instant.now()
        );

        EventEnvelope<UserRegisteredEvent> envelope = new EventEnvelope<>(
                UUID.randomUUID(),
                "UserRegistered",
                Instant.now(),
                CorrelationContext.getCorrelationId(),
                new EventEnvelope.Actor(user.getId(), "CUSTOMER"),
                new EventEnvelope.Resource("USER", user.getId()),
                eventData
        );

        outboxService.enqueue(envelope);
        log.info("Registered customer {} with username {}", user.getId(), user.getUsername());

        return user;
    }

    /**
     * Admin staff provisioning (ANALYST, ADMIN, AGENT).
     */
    @Transactional
    public User createStaffOrAgentUser(AdminCreateUserRequest request, UUID adminActorId) {
        if (userRepository.existsByEmail(request.email())) {
            throw new BusinessException(ErrorCode.EMAIL_ALREADY_EXISTS, "Email is already registered: " + request.email());
        }
        if (userRepository.existsByUsername(request.username())) {
            throw new BusinessException(ErrorCode.USERNAME_TAKEN, "Username is already taken: " + request.username());
        }
        if (userRepository.existsByPhone(request.phone())) {
            throw new BusinessException(ErrorCode.PHONE_ALREADY_EXISTS, "Phone number is already registered: " + request.phone());
        }

        UUID userId = UUID.randomUUID();
        User user = new User(
                userId,
                request.email(),
                request.username(),
                request.phone(),
                passwordEncoder.encode(request.password()),
                request.role(),
                request.accountKind()
        );

        user = userRepository.save(user);

        String displayName = (request.displayName() != null && !request.displayName().isBlank())
                ? request.displayName()
                : request.username();

        UserRegisteredEvent eventData = new UserRegisteredEvent(
                user.getId(),
                user.getEmail(),
                user.getUsername(),
                user.getPhone(),
                user.getRole(),
                user.getAccountKind(),
                displayName,
                Instant.now()
        );

        EventEnvelope<UserRegisteredEvent> envelope = new EventEnvelope<>(
                UUID.randomUUID(),
                "UserRegistered",
                Instant.now(),
                CorrelationContext.getCorrelationId(),
                new EventEnvelope.Actor(adminActorId, "ADMIN"),
                new EventEnvelope.Resource("USER", user.getId()),
                eventData
        );

        outboxService.enqueue(envelope);
        log.info("Admin created staff/agent user {} with role {}", user.getId(), user.getRole());

        return user;
    }

    /**
     * Login with lockout check (5 failures within 15 mins for identifier + IP -> 429).
     */
    @Transactional
    public LoginResult login(LoginRequest request, String ipAddress, String deviceInfo) {
        String identifier = request.identifier().trim();
        Instant windowStart = Instant.now().minus(lockoutWindowMinutes, ChronoUnit.MINUTES);

        long failedAttempts = loginAttemptRepository.countFailedAttemptsSince(identifier, ipAddress, windowStart);
        if (failedAttempts >= maxFailedAttempts) {
            log.warn("Login rejected for identifier {} from IP {}: account locked due to {} recent failures", 
                    identifier, ipAddress, failedAttempts);
            throw new BusinessException(ErrorCode.ACCOUNT_LOCKED, "Too many failed login attempts. Please try again later.");
        }

        Optional<User> userOpt = findByIdentifier(identifier);
        if (userOpt.isEmpty() || !passwordEncoder.matches(request.password(), userOpt.get().getPasswordHash())) {
            loginAttemptService.recordAttempt(identifier, ipAddress, false, "INVALID_CREDENTIALS");
            throw new BusinessException(ErrorCode.INVALID_CREDENTIALS, "Invalid identifier or password");
        }

        User user = userOpt.get();
        if (!user.isEnabled()) {
            loginAttemptService.recordAttempt(identifier, ipAddress, false, "ACCOUNT_DISABLED");
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Account is disabled");
        }

        loginAttemptService.recordAttempt(identifier, ipAddress, true, null);

        // Issue tokens
        List<String> roles = List.of(user.getRole().name());
        String accessToken = jwtService.issueAccessToken(user.getId(), roles);

        String rawRefreshToken = generateSecureOpaqueToken();
        String tokenHash = PasswordConfig.sha256Hex(rawRefreshToken);

        RefreshToken refreshToken = new RefreshToken(
                UUID.randomUUID(),
                user,
                tokenHash,
                deviceInfo,
                ipAddress,
                Instant.now().plusSeconds(refreshTokenTtlSeconds)
        );
        refreshTokenRepository.save(refreshToken);

        AuthResponse authResponse = AuthResponse.of(
                accessToken,
                jwtService.getAccessTokenTtlSeconds(),
                user.getId(),
                user.getUsername(),
                roles
        );

        return new LoginResult(authResponse, rawRefreshToken);
    }

    /**
     * Rotating refresh token with reuse detection.
     */
    @Transactional
    public LoginResult refreshToken(String rawRefreshToken, String ipAddress, String deviceInfo) {
        if (rawRefreshToken == null || rawRefreshToken.isBlank()) {
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Refresh token is missing");
        }

        String tokenHash = PasswordConfig.sha256Hex(rawRefreshToken);
        Optional<RefreshToken> tokenOpt = refreshTokenRepository.findByTokenHash(tokenHash);

        if (tokenOpt.isEmpty()) {
            log.warn("Unknown refresh token presented from IP {}", ipAddress);
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Invalid refresh token");
        }

        RefreshToken token = tokenOpt.get();

        // Reuse detection: If previously replaced or revoked, revoke entire user chain!
        if (token.getReplacedBy() != null || token.isRevoked()) {
            log.error("ALERT: Reuse of revoked/replaced refresh token detected for user {}! Revoking all sessions.", token.getUser().getId());
            refreshTokenRepository.revokeAllForUser(token.getUser(), Instant.now());
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Token reuse detected. Session terminated.");
        }

        if (token.isExpired()) {
            token.setRevokedAt(Instant.now());
            refreshTokenRepository.save(token);
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Refresh token has expired");
        }

        User user = token.getUser();
        if (!user.isEnabled()) {
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Account is disabled");
        }

        // Issue new access token and new rotated refresh token
        String newAccessToken = jwtService.issueAccessToken(user.getId(), List.of(user.getRole().name()));
        String newRawRefreshToken = generateSecureOpaqueToken();
        String newTokenHash = PasswordConfig.sha256Hex(newRawRefreshToken);

        UUID newRefreshTokenId = UUID.randomUUID();
        RefreshToken newRefreshToken = new RefreshToken(
                newRefreshTokenId,
                user,
                newTokenHash,
                deviceInfo,
                ipAddress,
                Instant.now().plusSeconds(refreshTokenTtlSeconds)
        );

        // Mark current token replaced
        token.setReplacedBy(newRefreshTokenId);
        token.setRevokedAt(Instant.now());

        refreshTokenRepository.save(token);
        refreshTokenRepository.save(newRefreshToken);

        AuthResponse authResponse = AuthResponse.of(
                newAccessToken,
                jwtService.getAccessTokenTtlSeconds(),
                user.getId(),
                user.getUsername(),
                List.of(user.getRole().name())
        );

        return new LoginResult(authResponse, newRawRefreshToken);
    }

    /**
     * Revoke refresh token on logout.
     */
    @Transactional
    public void logout(String rawRefreshToken) {
        if (rawRefreshToken == null || rawRefreshToken.isBlank()) {
            return;
        }
        String tokenHash = PasswordConfig.sha256Hex(rawRefreshToken);
        refreshTokenRepository.findByTokenHash(tokenHash).ifPresent(token -> {
            token.setRevokedAt(Instant.now());
            refreshTokenRepository.save(token);
        });
    }

    /**
     * Machine-to-machine service token generation.
     */
    @Transactional(readOnly = true)
    public ServiceTokenResponse issueServiceToken(ServiceTokenRequest request) {
        ServiceClient client = serviceClientRepository.findById(request.clientId())
                .orElseThrow(() -> new BusinessException(ErrorCode.UNAUTHORIZED, "Invalid client credentials"));

        String hash = PasswordConfig.sha256Hex(request.clientSecret());
        if (!client.getSecretHash().equals(hash)) {
            throw new BusinessException(ErrorCode.UNAUTHORIZED, "Invalid client credentials");
        }

        String token = jwtService.issueServiceToken(client.getClientId(), client.getRole());
        return ServiceTokenResponse.of(token, 300);
    }

    private Optional<User> findByIdentifier(String identifier) {
        Optional<User> byEmail = userRepository.findByEmail(identifier);
        if (byEmail.isPresent()) return byEmail;

        Optional<User> byUsername = userRepository.findByUsername(identifier);
        if (byUsername.isPresent()) return byUsername;

        return userRepository.findByPhone(identifier);
    }

    private String generateSecureOpaqueToken() {
        byte[] bytes = new byte[32];
        SECURE_RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}

