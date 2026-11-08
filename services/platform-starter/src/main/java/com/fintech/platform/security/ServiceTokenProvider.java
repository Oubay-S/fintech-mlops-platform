package com.fintech.platform.security;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.time.Instant;
import java.util.Map;

/**
 * Manages and caches internal machine-to-machine 'SERVICE'-role JWT tokens.
 * Automatically requests a new service token from auth-service before expiry.
 */
@Component
@ConditionalOnProperty(name = "app.security.service-token.enabled", havingValue = "true")
public class ServiceTokenProvider {

    private static final Logger log = LoggerFactory.getLogger(ServiceTokenProvider.class);

    @Value("${app.security.service-token.auth-url:http://auth-service:8081/internal/auth/service-token}")
    private String authUrl;

    @Value("${app.security.service-token.client-id:}")
    private String clientId;

    @Value("${app.security.service-token.client-secret:}")
    private String clientSecret;

    private final RestTemplate restTemplate;

    private String cachedToken;
    private Instant expiresAt;

    public ServiceTokenProvider() {
        this.restTemplate = new RestTemplate();
    }

    /**
     * Returns a valid SERVICE-role JWT, obtaining a fresh one if expired.
     */
    public synchronized String getServiceToken() {
        if (cachedToken != null && expiresAt != null && Instant.now().isBefore(expiresAt.minusSeconds(30))) {
            return cachedToken;
        }

        refreshServiceToken();
        return cachedToken;
    }

    private void refreshServiceToken() {
        log.info("Requesting new internal SERVICE token from auth-service for client: {}", clientId);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        Map<String, String> body = Map.of(
                "clientId", clientId,
                "clientSecret", clientSecret
        );

        HttpEntity<Map<String, String>> request = new HttpEntity<>(body, headers);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(authUrl, request, Map.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                this.cachedToken = (String) response.getBody().get("accessToken");
                // Service token has 5 minutes TTL -> refresh after 4.5 minutes
                this.expiresAt = Instant.now().plusSeconds(270);
                log.info("Successfully acquired SERVICE token, expires at: {}", expiresAt);
            } else {
                throw new IllegalStateException("Failed to obtain service token: HTTP " + response.getStatusCode());
            }
        } catch (Exception ex) {
            log.error("Error communicating with auth-service for service token: {}", ex.getMessage());
            throw new IllegalStateException("Auth service unreachable for internal token", ex);
        }
    }
}

