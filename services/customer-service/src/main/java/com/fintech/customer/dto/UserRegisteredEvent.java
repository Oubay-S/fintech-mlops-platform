package com.fintech.customer.dto;

import java.time.Instant;
import java.util.UUID;

public record UserRegisteredEvent(
        UUID userId,
        String email,
        String username,
        String phone,
        String role,
        String accountKind,
        String displayName,
        Instant occurredAt
) {
}

