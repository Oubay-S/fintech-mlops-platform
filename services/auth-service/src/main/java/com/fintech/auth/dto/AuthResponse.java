package com.fintech.auth.dto;

import java.util.List;
import java.util.UUID;

public record AuthResponse(
        String accessToken,
        String tokenType,
        long expiresIn,
        UUID userId,
        String username,
        List<String> roles
) {
    public static AuthResponse of(String accessToken, long expiresIn, UUID userId, String username, List<String> roles) {
        return new AuthResponse(accessToken, "Bearer", expiresIn, userId, username, roles);
    }
}

