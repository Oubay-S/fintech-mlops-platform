package com.fintech.auth.dto;

import com.fintech.auth.domain.AccountKind;
import com.fintech.auth.domain.Role;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record AdminCreateUserRequest(
        @NotBlank @Email String email,
        @NotBlank @Size(min = 3, max = 50) String username,
        @NotBlank String phone,
        @NotBlank @Size(min = 10, message = "Password must be at least 10 characters") String password,
        @NotNull Role role,
        @NotNull AccountKind accountKind,
        String displayName
) {
    @AssertTrue(message = "Only AGENT, ANALYST, or ADMIN roles can be provisioned by admin")
    public boolean isValidRole() {
        return role == Role.AGENT || role == Role.ANALYST || role == Role.ADMIN;
    }
}

