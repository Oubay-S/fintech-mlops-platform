package com.fintech.platform.outbox;

import com.fintech.platform.security.ServiceTokenProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

/**
 * Fallback OutboxPublisher implementation using plain HTTP POST to /internal/events.
 * Active when RabbitMQ is absent or fallback is selected.
 */
@Component
@ConditionalOnMissingBean(OutboxPublisher.class)
public class HttpOutboxPublisher implements OutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(HttpOutboxPublisher.class);

    @Value("${app.outbox.http.endpoint:http://localhost:8080/internal/events}")
    private String endpoint;

    private final RestTemplate restTemplate;
    private final ObjectProvider<ServiceTokenProvider> serviceTokenProvider;

    @Autowired
    public HttpOutboxPublisher(ObjectProvider<ServiceTokenProvider> serviceTokenProvider) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout((int) Duration.ofSeconds(3).toMillis());
        factory.setReadTimeout((int) Duration.ofSeconds(5).toMillis());
        this.restTemplate = new RestTemplate(factory);
        this.serviceTokenProvider = serviceTokenProvider;
    }

    public HttpOutboxPublisher(RestTemplate restTemplate, ObjectProvider<ServiceTokenProvider> serviceTokenProvider) {
        this.restTemplate = restTemplate;
        this.serviceTokenProvider = serviceTokenProvider;
    }

    @Override
    public void publish(OutboxEvent event) {
        log.debug("HTTP fallback: delivering outbox event [{}] to {}", event.getEventId(), endpoint);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Event-Type", event.getType());
        headers.set("X-Event-Id", event.getEventId().toString());

        // Attach SERVICE bearer token if ServiceTokenProvider is configured; propagate on failure
        if (serviceTokenProvider != null) {
            ServiceTokenProvider provider = serviceTokenProvider.getIfAvailable();
            if (provider != null) {
                headers.setBearerAuth(provider.getServiceToken());
            }
        }

        HttpEntity<String> request = new HttpEntity<>(event.getPayload(), headers);
        
        // Execute POST and propagate failures to prevent false delivery acknowledgment
        ResponseEntity<Void> response = restTemplate.postForEntity(endpoint, request, Void.class);
        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new IllegalStateException("HTTP outbox delivery failed with HTTP status: " + response.getStatusCode());
        }
    }
}

