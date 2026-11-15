package com.fintech.customer.dto;

import com.fintech.customer.domain.AccountStatus;

import java.time.Instant;
import java.util.UUID;

public record AccountStatusChangedEvent(
        UUID userId,
        AccountStatus previousStatus,
        AccountStatus newStatus,
        String reason,
        Instant occurredAt
) {
}

