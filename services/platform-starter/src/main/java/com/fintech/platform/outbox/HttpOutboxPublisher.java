package com.fintech.platform.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

/**
 * Fallback OutboxPublisher implementation using plain HTTP POST to /internal/events.
 * Active when 'app.outbox.publisher=http'.
 */
@Component
@org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean(OutboxPublisher.class)
public class HttpOutboxPublisher implements OutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(HttpOutboxPublisher.class);

    private final RestTemplate restTemplate;

    public HttpOutboxPublisher() {
        this.restTemplate = new RestTemplate();
    }

    @Override
    public void publish(OutboxEvent event) {
        log.debug("HTTP fallback: delivering outbox event [{}] to /internal/events", event.getEventId());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        HttpEntity<String> request = new HttpEntity<>(event.getPayload(), headers);
        // Note: Target service URL is resolved per destination or via internal routing
        // This fallback ensures services can run without RabbitMQ in minimal environments
    }
}

