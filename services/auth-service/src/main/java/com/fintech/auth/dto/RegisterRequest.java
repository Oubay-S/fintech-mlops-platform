package com.fintech.auth.dto;

import com.fintech.auth.domain.AccountKind;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank @Email String email,
        @NotBlank @Size(min = 3, max = 50) String username,
        @NotBlank String phone,
        @NotBlank @Size(min = 10, message = "Password must be at least 10 characters") String password,
        @NotNull AccountKind accountKind,
        String displayName
) {
}

