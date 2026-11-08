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
import org.springframework.amqp.core.AmqpTemplate;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Spring Boot AutoConfiguration entry point for platform-starter.
 * Automatically loads shared error handling, security, correlation filter, outbox, and observability.
 */
@AutoConfiguration
@EnableScheduling
@Import(ObservabilityConfig.class)
public class PlatformStarterAutoConfiguration {

    /**
     * Servlet-specific web components (Servlet filter & MVC exception advice).
     * Protected against WebFlux/reactive environments (e.g. Spring Cloud Gateway).
     */
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
    @Import({CorrelationIdFilter.class, GlobalExceptionHandler.class})
    static class ServletWebConfiguration {
    }

    /**
     * Outbox components are enabled only when JPA persistence is present.
     */
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnClass(name = "jakarta.persistence.EntityManagerFactory")
    @Import({OutboxService.class, OutboxPoller.class, HttpOutboxPublisher.class})
    static class OutboxConfiguration {
    }

    /**
     * RabbitMQ event publishing enabled when Spring AMQP is on the classpath.
     */
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnClass(AmqpTemplate.class)
    @Import(RabbitMqOutboxPublisher.class)
    static class RabbitMqConfiguration {
    }

    /**
     * Resource server security filter chain and service token provider.
     */
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnClass(SecurityFilterChain.class)
    @Import({PlatformSecurityConfig.class, ServiceTokenProvider.class})
    static class SecurityConfiguration {
    }
}
