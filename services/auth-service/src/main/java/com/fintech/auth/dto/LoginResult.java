package com.fintech.auth.dto;

public record LoginResult(
        AuthResponse response,
        String rawRefreshToken
) {
}

