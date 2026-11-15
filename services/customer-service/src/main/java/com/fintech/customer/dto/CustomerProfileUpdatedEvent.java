package com.fintech.customer.dto;

import java.time.Instant;
import java.util.UUID;

public record CustomerProfileUpdatedEvent(
        UUID userId,
        String displayName,
        Instant occurredAt
) {
}

