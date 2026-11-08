package com.fintech.auth.dto;

public record ServiceTokenResponse(
        String accessToken,
        String tokenType,
        long expiresIn
) {
    public static ServiceTokenResponse of(String accessToken, long expiresIn) {
        return new ServiceTokenResponse(accessToken, "Bearer", expiresIn);
    }
}

