package com.fintech.auth.dto;

import jakarta.validation.constraints.NotBlank;

public record LoginRequest(
        @NotBlank String identifier, // username, email, or phone
        @NotBlank String password
) {
}

