package com.fintech.customer.dto;

import java.time.Instant;
import java.util.UUID;

public record ReceiverLookedUpEvent(
        UUID callerId,
        UUID receiverId,
        String identifierHash,
        Instant occurredAt
) {
}
