package com.fintech.platform.outbox;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Service to enqueue events into the outbox table within the caller's active database transaction.
 */
@Service
public class OutboxService {

    private final OutboxRepository outboxRepository;
    private final ObjectMapper objectMapper;

    public OutboxService(OutboxRepository outboxRepository, ObjectMapper objectMapper) {
        this.outboxRepository = outboxRepository;
        this.objectMapper = objectMapper;
    }

    /**
     * Enqueues an event envelope into the outbox table.
     * Must be called inside a @Transactional method so it commits atomically with business data.
     */
    @Transactional
    public <T> OutboxEvent enqueue(EventEnvelope<T> envelope) {
        try {
            String payloadJson = objectMapper.writeValueAsString(envelope);
            OutboxEvent outboxEvent = new OutboxEvent(
                    envelope.getEventId(),
                    envelope.getType(),
                    payloadJson
            );
            return outboxRepository.save(outboxEvent);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Failed to serialize outbox event payload", e);
        }
    }
}

