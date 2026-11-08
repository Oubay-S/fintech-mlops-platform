package com.fintech.auth.dto;

import com.fintech.auth.domain.AccountKind;
import com.fintech.auth.domain.Role;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record AdminCreateUserRequest(
        @NotBlank @Email String email,
        @NotBlank @Size(min = 3, max = 50) String username,
        @NotBlank String phone,
        @NotBlank @Size(min = 8) String password,
        @NotNull Role role,
        @NotNull AccountKind accountKind,
        String displayName
) {
}

