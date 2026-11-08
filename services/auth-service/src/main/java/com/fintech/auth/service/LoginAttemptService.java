package com.fintech.auth.service;

import com.fintech.auth.domain.LoginAttempt;
import com.fintech.auth.repository.LoginAttemptRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

@Service
public class LoginAttemptService {

    private final LoginAttemptRepository loginAttemptRepository;

    public LoginAttemptService(LoginAttemptRepository loginAttemptRepository) {
        this.loginAttemptRepository = loginAttemptRepository;
    }

    /**
     * ALWAYS commits the attempt in its own independent transaction,
     * even if the calling AuthService.login method throws a BusinessException!
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordAttempt(String identifier, String ipAddress, boolean wasSuccessful, String failureReason) {
        LoginAttempt attempt = new LoginAttempt(
                UUID.randomUUID(),
                identifier,
                ipAddress,
                wasSuccessful,
                failureReason
        );
        loginAttemptRepository.save(attempt);
    }
}

