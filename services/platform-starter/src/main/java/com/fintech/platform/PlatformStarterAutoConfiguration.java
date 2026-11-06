package com.fintech.platform;

import com.fintech.platform.correlation.CorrelationIdFilter;
import com.fintech.platform.error.GlobalExceptionHandler;
import com.fintech.platform.observability.ObservabilityConfig;
import com.fintech.platform.outbox.HttpOutboxPublisher;
import com.fintech.platform.outbox.OutboxPoller;
import com.fintech.platform.outbox.OutboxService;
import com.fintech.platform.outbox.RabbitMqOutboxPublisher;
import com.fintech.platform.security.PlatformSecurityConfig;
import com.fintech.platform.security.ServiceTokenProvider;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Import;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Spring Boot AutoConfiguration entry point for platform-starter.
 * Automatically loads shared error handling, security, correlation filter, outbox, and observability.
 */
@AutoConfiguration
@ConditionalOnWebApplication
@EnableScheduling
@Import({
        CorrelationIdFilter.class,
        GlobalExceptionHandler.class,
        PlatformSecurityConfig.class,
        ObservabilityConfig.class,
        OutboxService.class,
        OutboxPoller.class,
        RabbitMqOutboxPublisher.class,
        HttpOutboxPublisher.class,
        ServiceTokenProvider.class
})
public class PlatformStarterAutoConfiguration {
}
