package com.fintech.customer.dto;

import jakarta.validation.constraints.NotBlank;

public record ReceiverLookupRequest(
        @NotBlank(message = "Identifier cannot be blank")
        String identifier
) {
}

