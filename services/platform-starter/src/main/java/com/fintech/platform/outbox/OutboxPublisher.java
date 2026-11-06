package com.fintech.platform.outbox;

/**
 * Interface representing the physical delivery mechanism of outbox events
 * (either RabbitMQ topic exchange or HTTP fallback).
 */
public interface OutboxPublisher {

    /**
     * Publishes an outbox event.
     *
     * @param event the event to deliver
     * @throws Exception if publication fails (triggering backoff/retry)
     */
    void publish(OutboxEvent event) throws Exception;
}

