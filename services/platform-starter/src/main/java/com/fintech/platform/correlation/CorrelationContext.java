package com.fintech.platform.correlation;

import org.slf4j.MDC;

/**
 * Utility helper to conveniently access or set the current correlation ID programmatically.
 */
public final class CorrelationContext {

    private CorrelationContext() {
    }

    public static String getCorrelationId() {
        return MDC.get(CorrelationIdFilter.MDC_KEY);
    }

    public static void setCorrelationId(String correlationId) {
        if (correlationId != null) {
            MDC.put(CorrelationIdFilter.MDC_KEY, correlationId);
        }
    }

    public static void clear() {
        MDC.remove(CorrelationIdFilter.MDC_KEY);
    }
}

