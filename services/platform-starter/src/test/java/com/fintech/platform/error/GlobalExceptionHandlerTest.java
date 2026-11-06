package com.fintech.platform.error;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import static org.assertj.core.api.Assertions.assertThat;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    void shouldFormatBusinessExceptionAsProblemDetail() {
        BusinessException ex = new BusinessException(
                ErrorCode.INSUFFICIENT_FUNDS,
                "Available balance is lower than the requested amount."
        );

        ResponseEntity<ProblemDetail> response = handler.handleBusinessException(ex);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getHeaders().getContentType().toString()).contains("application/problem+json");

        ProblemDetail body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.getCode()).isEqualTo("INSUFFICIENT_FUNDS");
        assertThat(body.getStatus()).isEqualTo(422);
        assertThat(body.getType()).isEqualTo("https://fintech.local/errors/insufficient-funds");
        assertThat(body.getDetail()).isEqualTo("Available balance is lower than the requested amount.");
    }
}

