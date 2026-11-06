package com.fintech.platform.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.AmqpTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * Default OutboxPublisher implementation using RabbitMQ topic exchange 'fintech.events'.
 * Active when 'app.outbox.publisher=rabbitmq' (or by default when app.outbox.publisher is unset).
 *
 * Routing key format: <service>.<resource>.<event> (e.g. "transaction.transfer.completed")
 */
@Component
@ConditionalOnProperty(name = "app.outbox.publisher", havingValue = "rabbitmq", matchIfMissing = true)
public class RabbitMqOutboxPublisher implements OutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(RabbitMqOutboxPublisher.class);
    public static final String EXCHANGE_NAME = "fintech.events";

    private final AmqpTemplate amqpTemplate;

    public RabbitMqOutboxPublisher(AmqpTemplate amqpTemplate) {
        this.amqpTemplate = amqpTemplate;
    }

    @Override
    public void publish(OutboxEvent event) {
        String routingKey = computeRoutingKey(event.getType());
        log.debug("Publishing outbox event [{}] to exchange '{}' with routingKey '{}'",
                event.getEventId(), EXCHANGE_NAME, routingKey);

        amqpTemplate.convertAndSend(EXCHANGE_NAME, routingKey, event.getPayload());
    }

    /**
     * Converts event type (e.g. "TransferCompleted" or "transaction.transfer.completed")
     * into a consistent topic routing key.
     */
    private String computeRoutingKey(String eventType) {
        if (eventType.contains(".")) {
            return eventType.toLowerCase();
        }
        // Fallback: convert PascalCase to dot-separated lowercase (e.g. "TransferCompleted" -> "events.transfercompleted")
        return "events." + eventType.toLowerCase();
    }
}

