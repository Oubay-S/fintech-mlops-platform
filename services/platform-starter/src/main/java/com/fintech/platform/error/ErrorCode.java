package com.fintech.platform.error;

import org.springframework.http.HttpStatus;

/**
 * Standard error codes defined across the platform (Conception Plan Section 19.4).
 */
public enum ErrorCode {
    VALIDATION_FAILED(HttpStatus.BAD_REQUEST, "Request body or parameter validation failed"),
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "Authentication failed or token invalid"),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "Invalid identifier or password"),
    UNAUTHENTICATED(HttpStatus.UNAUTHORIZED, "Missing or invalid token"),
    TOKEN_EXPIRED(HttpStatus.UNAUTHORIZED, "Access or refresh token expired"),
    FORBIDDEN(HttpStatus.FORBIDDEN, "Insufficient permissions for requested resource"),
    ACCOUNT_RESTRICTED(HttpStatus.FORBIDDEN, "Account is restricted or blocked"),
    NOT_FOUND(HttpStatus.NOT_FOUND, "Requested resource not found or not owned by user"),
    RECEIVER_NOT_FOUND(HttpStatus.NOT_FOUND, "Target receiver not found"),
    PROVISIONING(HttpStatus.NOT_FOUND, "Account profile or wallet is still provisioning"),
    REQUEST_IN_PROGRESS(HttpStatus.CONFLICT, "An identical request with this idempotency key is currently processing"),
    INVALID_STATE_TRANSITION(HttpStatus.CONFLICT, "Action not allowed in the current resource state"),
    REQUEST_EXPIRED(HttpStatus.CONFLICT, "Payment request has expired"),
    CASE_ALREADY_CLAIMED(HttpStatus.CONFLICT, "Review case is already claimed by another analyst"),
    INVALID_RECEIVER_KIND(HttpStatus.UNPROCESSABLE_ENTITY, "Receiver kind does not match transaction type"),
    INSUFFICIENT_FUNDS(HttpStatus.UNPROCESSABLE_ENTITY, "Available balance is lower than the requested amount"),
    IDEMPOTENCY_KEY_REUSED(HttpStatus.UNPROCESSABLE_ENTITY, "Idempotency key reused with a different request payload"),
    LIMIT_EXCEEDED(HttpStatus.UNPROCESSABLE_ENTITY, "Amount exceeds system configured maximum limits"),
    EMAIL_ALREADY_EXISTS(HttpStatus.CONFLICT, "Email address is already in use"),
    USERNAME_TAKEN(HttpStatus.CONFLICT, "Username is already taken"),
    PHONE_ALREADY_EXISTS(HttpStatus.CONFLICT, "Phone number is already in use"),
    ACCOUNT_LOCKED(HttpStatus.TOO_MANY_REQUESTS, "Account locked due to excessive failed attempts"),
    RATE_LIMITED(HttpStatus.TOO_MANY_REQUESTS, "Rate limit exceeded"),
    TEMPORARILY_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "Service temporarily unavailable due to downstream overload"),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "An unexpected server error occurred");

    private final HttpStatus httpStatus;
    private final String defaultTitle;

    ErrorCode(HttpStatus httpStatus, String defaultTitle) {
        this.httpStatus = httpStatus;
        this.defaultTitle = defaultTitle;
    }

    public HttpStatus getHttpStatus() {
        return httpStatus;
    }

    public String getDefaultTitle() {
        return defaultTitle;
    }
}

