package com.fintech.customer.dto;

import java.util.UUID;

public record ReceiverLookupResponse(
        UUID receiverId,
        String maskedName
) {
}

