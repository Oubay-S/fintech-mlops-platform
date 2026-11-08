package com.fintech.platform.observability;

import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.boot.actuate.autoconfigure.metrics.MeterRegistryCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;

/**
 * Common configuration for Prometheus/Micrometer metrics.
 * Attaches 'service' and 'instance' tags to all emitted metrics across all microservices.
 */
@Configuration
public class ObservabilityConfig {

    @Bean
    public MeterRegistryCustomizer<MeterRegistry> meterRegistryCustomizer(Environment environment) {
        String serviceName = environment.getProperty("spring.application.name", "unknown-service");
        String port = environment.getProperty("server.port", "8080");

        return registry -> registry.config()
                .commonTags("service", serviceName)
                .commonTags("instance", serviceName + ":" + port);
    }
}

