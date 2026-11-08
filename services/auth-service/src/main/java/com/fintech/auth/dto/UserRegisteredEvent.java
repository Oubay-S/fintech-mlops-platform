package com.fintech.auth.dto;

import com.fintech.auth.domain.AccountKind;
import com.fintech.auth.domain.Role;

import java.time.Instant;
import java.util.UUID;

public record UserRegisteredEvent(
        UUID userId,
        String email,
        String username,
        String phone,
        Role role,
        AccountKind accountKind,
        String displayName,
        Instant occurredAt
) {
}

