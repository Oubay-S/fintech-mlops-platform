package com.fintech.customer.dto;

import com.fintech.customer.domain.AccountStatus;
import jakarta.validation.constraints.NotNull;

public record UpdateStatusRequest(
        @NotNull(message = "Account status is required")
        AccountStatus status,
        String reason
) {
}

