package com.fintech.platform.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fintech.platform.correlation.CorrelationContext;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.error.ProblemDetail;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.access.AccessDeniedHandler;

import java.io.IOException;

/**
 * Provides standard RFC 7807 (application/problem+json) error responses for
 * Spring Security filter chain failures (401 unauthenticated and 403 forbidden).
 */
public final class SecurityProblemSupport {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private SecurityProblemSupport() {
    }

    public static AuthenticationEntryPoint authenticationEntryPoint() {
        return (request, response, authException) -> writeProblem(
                response,
                HttpStatus.UNAUTHORIZED,
                ErrorCode.UNAUTHENTICATED,
                "Authentication is required to access this resource"
        );
    }

    public static AccessDeniedHandler accessDeniedHandler() {
        return (request, response, accessDeniedException) -> writeProblem(
                response,
                HttpStatus.FORBIDDEN,
                ErrorCode.FORBIDDEN,
                "You do not have permission to access this resource"
        );
    }

    private static void writeProblem(HttpServletResponse response,
                                     HttpStatus status,
                                     ErrorCode errorCode,
                                     String detail) throws IOException {
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);

        String slug = errorCode.name().toLowerCase().replace('_', '-');
        ProblemDetail problem = new ProblemDetail(
                "https://fintech.local/errors/" + slug,
                errorCode.getDefaultTitle(),
                status.value(),
                errorCode.name(),
                detail,
                CorrelationContext.getCorrelationId(),
                null
        );

        OBJECT_MAPPER.writeValue(response.getOutputStream(), problem);
    }
}

