package com.fintech.auth.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fintech.auth.dto.AccountStatusChangedEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.UUID;

@Component
@ConditionalOnClass(RabbitListener.class)
public class AuthEventListener {

    private static final Logger log = LoggerFactory.getLogger(AuthEventListener.class);

    private final AuthService authService;
    private final ObjectMapper objectMapper;

    public AuthEventListener(AuthService authService, ObjectMapper objectMapper) {
        this.authService = authService;
        this.objectMapper = objectMapper;
    }

    @RabbitListener(queues = "${app.messaging.queues.auth-events:auth.events}")
    public void onMessage(String messagePayload) {
        String eventType = "unknown";
        try {
            JsonNode root = objectMapper.readTree(messagePayload);
            eventType = root.path("type").asText("unknown");

            if ("customer.account.status-changed".equalsIgnoreCase(eventType)) {
                JsonNode dataNode = root.path("data");
                AccountStatusChangedEvent event = parseAccountStatusChangedEvent(dataNode);
                if (event != null && event.userId() != null) {
                    authService.handleAccountStatusChanged(event.userId(), event.newStatus(), event.reason());
                }
            } else {
                log.debug("AuthEventListener ignoring unhandled event type: {}", eventType);
            }
        } catch (Exception e) {
            log.error("Failed to process AMQP message for event type [{}]: {}", eventType, e.getMessage());
            throw new RuntimeException("Error processing event message", e);
        }
    }

    public AccountStatusChangedEvent parseAccountStatusChangedEvent(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) {
            return null;
        }

        try {
            return objectMapper.treeToValue(node, AccountStatusChangedEvent.class);
        } catch (Exception e) {
            UUID userId = UUID.fromString(node.path("userId").asText());
            String prevStatus = node.path("previousStatus").asText("ACTIVE");
            String newStatus = node.path("newStatus").asText("ACTIVE");
            String reason = node.path("reason").asText(null);
            Instant occurredAt = node.has("occurredAt")
                    ? Instant.parse(node.path("occurredAt").asText())
                    : Instant.now();

            return new AccountStatusChangedEvent(userId, prevStatus, newStatus, reason, occurredAt);
        }
    }
}
