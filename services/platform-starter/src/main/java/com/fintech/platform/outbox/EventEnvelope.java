package com.fintech.platform.outbox;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.time.Instant;
import java.util.UUID;

/**
 * Standard event envelope for all asynchronous domain events across the platform (Conception Plan Section 15.3).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class EventEnvelope<T> {

    private UUID eventId;
    private String type;
    private Instant occurredAt;
    private String correlationId;
    private Actor actor;
    private Resource resource;
    private T data;

    public EventEnvelope() {
    }

    public EventEnvelope(UUID eventId, String type, Instant occurredAt, String correlationId, Actor actor, Resource resource, T data) {
        this.eventId = eventId;
        this.type = type;
        this.occurredAt = occurredAt;
        this.correlationId = correlationId;
        this.actor = actor;
        this.resource = resource;
        this.data = data;
    }

    public static <T> EventEnvelope<T> create(String type, String correlationId, Actor actor, Resource resource, T data) {
        return new EventEnvelope<>(
                UUID.randomUUID(),
                type,
                Instant.now(),
                correlationId,
                actor,
                resource,
                data
        );
    }

    public UUID getEventId() {
        return eventId;
    }

    public void setEventId(UUID eventId) {
        this.eventId = eventId;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public Instant getOccurredAt() {
        return occurredAt;
    }

    public void setOccurredAt(Instant occurredAt) {
        this.occurredAt = occurredAt;
    }

    public String getCorrelationId() {
        return correlationId;
    }

    public void setCorrelationId(String correlationId) {
        this.correlationId = correlationId;
    }

    public Actor getActor() {
        return actor;
    }

    public void setActor(Actor actor) {
        this.actor = actor;
    }

    public Resource getResource() {
        return resource;
    }

    public void setResource(Resource resource) {
        this.resource = resource;
    }

    public T getData() {
        return data;
    }

    public void setData(T data) {
        this.data = data;
    }

    public static class Actor {
        private UUID id;
        private String role;

        public Actor() {
        }

        public Actor(UUID id, String role) {
            this.id = id;
            this.role = role;
        }

        public Actor(String id, String role) {
            this.id = id != null && !id.isBlank() ? (isUuid(id) ? UUID.fromString(id) : null) : null;
            this.role = role;
        }

        static boolean isUuid(String s) {
            try {
                UUID.fromString(s);
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        public UUID getId() {
            return id;
        }

        public void setId(UUID id) {
            this.id = id;
        }

        public String getRole() {
            return role;
        }

        public void setRole(String role) {
            this.role = role;
        }
    }

    public static class Resource {
        private String type;
        private UUID id;

        public Resource() {
        }

        public Resource(String type, UUID id) {
            this.type = type;
            this.id = id;
        }

        public Resource(String type, String id) {
            this.type = type;
            this.id = id != null && !id.isBlank() ? (Actor.isUuid(id) ? UUID.fromString(id) : null) : null;
        }

        public String getType() {
            return type;
        }

        public void setType(String type) {
            this.type = type;
        }

        public UUID getId() {
            return id;
        }

        public void setId(UUID id) {
            this.id = id;
        }
    }
}

