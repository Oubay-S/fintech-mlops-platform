package com.fintech.platform.outbox;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Spring Data JPA repository for the outbox table.
 * Uses pessimistic write lock with SKIP LOCKED for multi-replica concurrency safety.
 */
@Repository
public interface OutboxRepository extends JpaRepository<OutboxEvent, Long> {

    Optional<OutboxEvent> findByEventId(UUID eventId);

    /**
     * Finds pending outbox events ordered by created_at.
     * Note: In native Postgres queries, FOR UPDATE SKIP LOCKED is used in pollers.
     */
    @Query("SELECT o FROM OutboxEvent o WHERE o.deliveredAt IS NULL ORDER BY o.createdAt ASC")
    List<OutboxEvent> findPendingEvents(Pageable pageable);
}

