package com.fintech.platform.error;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.Collections;
import java.util.List;

/**
 * Standard RFC 7807 (Problem Details for HTTP APIs) error response model.
 */
@JsonInclude(JsonInclude.Include.NON_EMPTY)
public class ProblemDetail {

    private String type;
    private String title;
    private int status;
    private String code;
    private String detail;
    private String correlationId;
    private List<FieldErrorDetail> errors;

    public ProblemDetail() {
    }

    public ProblemDetail(String type, String title, int status, String code, String detail, String correlationId, List<FieldErrorDetail> errors) {
        this.type = type;
        this.title = title;
        this.status = status;
        this.code = code;
        this.detail = detail;
        this.correlationId = correlationId;
        this.errors = errors != null ? errors : Collections.emptyList();
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public int getStatus() {
        return status;
    }

    public void setStatus(int status) {
        this.status = status;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getDetail() {
        return detail;
    }

    public void setDetail(String detail) {
        this.detail = detail;
    }

    public String getCorrelationId() {
        return correlationId;
    }

    public void setCorrelationId(String correlationId) {
        this.correlationId = correlationId;
    }

    public List<FieldErrorDetail> getErrors() {
        return errors;
    }

    public void setErrors(List<FieldErrorDetail> errors) {
        this.errors = errors;
    }

    public static class FieldErrorDetail {
        private String field;
        private String message;

        public FieldErrorDetail() {
        }

        public FieldErrorDetail(String field, String message) {
            this.field = field;
            this.message = message;
        }

        public String getField() {
            return field;
        }

        public void setField(String field) {
            this.field = field;
        }

        public String getMessage() {
            return message;
        }

        public void setMessage(String message) {
            this.message = message;
        }
    }
}

