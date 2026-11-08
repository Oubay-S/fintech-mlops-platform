package com.fintech.auth.service;

import com.fintech.auth.domain.User;
import com.fintech.auth.repository.RefreshTokenRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;

/**
 * Handles refresh token revocation in an isolated transaction.
 * Propagation.REQUIRES_NEW ensures revocation commits immediately even if
 * the caller subsequently throws an unchecked exception (such as upon reuse detection).
 */
@Service
public class RefreshTokenService {

    private final RefreshTokenRepository refreshTokenRepository;

    public RefreshTokenService(RefreshTokenRepository refreshTokenRepository) {
        this.refreshTokenRepository = refreshTokenRepository;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void revokeAllForUser(User user) {
        refreshTokenRepository.revokeAllForUser(user, Instant.now());
    }
}

