package com.fintech.platform.error;

import org.springframework.http.HttpStatus;

import java.util.Collections;
import java.util.List;

/**
 * Base unchecked exception for all business/domain errors across services.
 */
public class BusinessException extends RuntimeException {

    private final ErrorCode errorCode;
    private final List<ProblemDetail.FieldErrorDetail> fieldErrors;

    public BusinessException(ErrorCode errorCode) {
        super(errorCode.getDefaultTitle());
        this.errorCode = errorCode;
        this.fieldErrors = Collections.emptyList();
    }

    public BusinessException(ErrorCode errorCode, String detail) {
        super(detail);
        this.errorCode = errorCode;
        this.fieldErrors = Collections.emptyList();
    }

    public BusinessException(ErrorCode errorCode, String detail, List<ProblemDetail.FieldErrorDetail> fieldErrors) {
        super(detail);
        this.errorCode = errorCode;
        this.fieldErrors = fieldErrors != null ? fieldErrors : Collections.emptyList();
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }

    public HttpStatus getHttpStatus() {
        return errorCode.getHttpStatus();
    }

    public List<ProblemDetail.FieldErrorDetail> getFieldErrors() {
        return fieldErrors;
    }
}

