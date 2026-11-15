package com.fintech.customer.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fintech.customer.dto.UserRegisteredEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.UUID;

@Component
@ConditionalOnClass(RabbitListener.class)
public class CustomerEventListener {

    private static final Logger log = LoggerFactory.getLogger(CustomerEventListener.class);

    private final CustomerService customerService;
    private final ObjectMapper objectMapper;

    public CustomerEventListener(CustomerService customerService, ObjectMapper objectMapper) {
        this.customerService = customerService;
        this.objectMapper = objectMapper;
    }

    @RabbitListener(queues = "${app.messaging.queues.customer-events:customer.events}")
    public void onMessage(String messagePayload) {
        try {
            JsonNode root = objectMapper.readTree(messagePayload);
            String eventType = root.path("type").asText();

            if ("auth.user.registered".equalsIgnoreCase(eventType)) {
                JsonNode dataNode = root.path("data");
                UserRegisteredEvent event = parseUserRegisteredEvent(dataNode);
                if (event != null) {
                    customerService.provisionCustomer(event);
                }
            } else {
                log.debug("CustomerEventListener ignoring unhandled event type: {}", eventType);
            }
        } catch (Exception e) {
            log.error("Failed to process AMQP message payload: {}", messagePayload, e);
            throw new RuntimeException("Error processing event message", e);
        }
    }

    public UserRegisteredEvent parseUserRegisteredEvent(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) {
            return null;
        }

        try {
            return objectMapper.treeToValue(node, UserRegisteredEvent.class);
        } catch (Exception e) {
            // Fallback manual parse in case of minor field mismatch
            UUID userId = UUID.fromString(node.path("userId").asText());
            String email = node.path("email").asText();
            String username = node.path("username").asText();
            String phone = node.path("phone").asText(null);
            String role = node.path("role").asText("CUSTOMER");
            String accountKind = node.path("accountKind").asText("PERSONAL");
            String displayName = node.path("displayName").asText(username);
            Instant occurredAt = node.has("occurredAt")
                    ? Instant.parse(node.path("occurredAt").asText())
                    : Instant.now();

            return new UserRegisteredEvent(userId, email, username, phone, role, accountKind, displayName, occurredAt);
        }
    }
}

