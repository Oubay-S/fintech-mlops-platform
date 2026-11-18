package com.fintech.auth.dto;

import java.time.Instant;
import java.util.UUID;

public record AccountStatusChangedEvent(
        UUID userId,
        String previousStatus,
        String newStatus,
        String reason,
        Instant occurredAt
) {
}
