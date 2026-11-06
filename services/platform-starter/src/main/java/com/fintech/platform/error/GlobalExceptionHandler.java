package com.fintech.platform.error;

import com.fintech.platform.correlation.CorrelationContext;
import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import java.util.ArrayList;
import java.util.List;

/**
 * Centralized exception handler that intercepts all exceptions and formats them
 * according to RFC 7807 (application/problem+json).
 */
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);
    private static final String PROBLEM_JSON = "application/problem+json";

    /**
     * Handles custom business and domain exceptions.
     */
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ProblemDetail> handleBusinessException(BusinessException ex) {
        log.warn("Business exception [{}]: {}", ex.getErrorCode().name(), ex.getMessage());
        return buildResponseEntity(
                ex.getErrorCode(),
                ex.getMessage(),
                ex.getFieldErrors()
        );
    }

    /**
     * Handles Spring Bean Validation errors (e.g. @Valid on @RequestBody DTOs).
     */
    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException ex,
                                                                  HttpHeaders headers,
                                                                  HttpStatusCode status,
                                                                  WebRequest request) {
        log.warn("Validation failed for request: {}", ex.getMessage());
        List<ProblemDetail.FieldErrorDetail> fieldErrors = new ArrayList<>();
        for (FieldError fieldError : ex.getBindingResult().getFieldErrors()) {
            fieldErrors.add(new ProblemDetail.FieldErrorDetail(
                    fieldError.getField(),
                    fieldError.getDefaultMessage()
            ));
        }

        ProblemDetail problem = createProblemDetail(
                ErrorCode.VALIDATION_FAILED,
                "One or more fields failed validation requirements",
                fieldErrors
        );

        HttpHeaders problemHeaders = new HttpHeaders();
        problemHeaders.setContentType(MediaType.parseMediaType(PROBLEM_JSON));
        return new ResponseEntity<>(problem, problemHeaders, HttpStatus.BAD_REQUEST);
    }

    /**
     * Handles JPA/Hibernate constraint violations.
     */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ProblemDetail> handleConstraintViolation(ConstraintViolationException ex) {
        log.warn("Constraint violation: {}", ex.getMessage());
        List<ProblemDetail.FieldErrorDetail> fieldErrors = new ArrayList<>();
        ex.getConstraintViolations().forEach(violation ->
                fieldErrors.add(new ProblemDetail.FieldErrorDetail(
                        violation.getPropertyPath().toString(),
                        violation.getMessage()
                ))
        );

        return buildResponseEntity(
                ErrorCode.VALIDATION_FAILED,
                "Constraint validation failed",
                fieldErrors
        );
    }

    /**
     * Handles Spring Security access denied (403 Forbidden).
     */
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ProblemDetail> handleAccessDenied(AccessDeniedException ex) {
        log.warn("Access denied: {}", ex.getMessage());
        return buildResponseEntity(
                ErrorCode.FORBIDDEN,
                "You do not have permission to access this resource",
                null
        );
    }

    /**
     * Handles unauthenticated requests (401 Unauthorized).
     */
    @ExceptionHandler(AuthenticationException.class)
    public ResponseEntity<ProblemDetail> handleAuthenticationException(AuthenticationException ex) {
        log.warn("Authentication failed: {}", ex.getMessage());
        return buildResponseEntity(
                ErrorCode.UNAUTHENTICATED,
                "Authentication is required to access this resource",
                null
        );
    }

    /**
     * Fallback for unexpected system exceptions (500 Internal Server Error).
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ProblemDetail> handleGenericException(Exception ex) {
        log.error("Unhandled unexpected exception", ex);
        return buildResponseEntity(
                ErrorCode.INTERNAL_SERVER_ERROR,
                "An unexpected internal error occurred. Please contact support with the correlation ID.",
                null
        );
    }

    private ResponseEntity<ProblemDetail> buildResponseEntity(ErrorCode errorCode,
                                                              String detail,
                                                              List<ProblemDetail.FieldErrorDetail> fieldErrors) {
        ProblemDetail problem = createProblemDetail(errorCode, detail, fieldErrors);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.parseMediaType(PROBLEM_JSON));
        return new ResponseEntity<>(problem, headers, errorCode.getHttpStatus());
    }

    private ProblemDetail createProblemDetail(ErrorCode errorCode,
                                              String detail,
                                              List<ProblemDetail.FieldErrorDetail> fieldErrors) {
        String slug = errorCode.name().toLowerCase().replace('_', '-');
        String typeUrl = "https://fintech.local/errors/" + slug;
        String correlationId = CorrelationContext.getCorrelationId();

        return new ProblemDetail(
                typeUrl,
                errorCode.getDefaultTitle(),
                errorCode.getHttpStatus().value(),
                errorCode.name(),
                detail,
                correlationId,
                fieldErrors
        );
    }
}

