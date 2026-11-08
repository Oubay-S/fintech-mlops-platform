package com.fintech.platform.outbox;

import jakarta.persistence.LockModeType;
import jakarta.persistence.QueryHint;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.QueryHints;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
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
     * Uses PESSIMISTIC_WRITE with lock timeout -2 (SKIP LOCKED) to ensure multi-replica safety
     * without blocking or duplicate concurrent processing.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints({
            @QueryHint(name = "jakarta.persistence.lock.timeout", value = "-2")
    })
    @Query("SELECT o FROM OutboxEvent o WHERE o.deliveredAt IS NULL ORDER BY o.createdAt ASC")
    List<OutboxEvent> findPendingEvents(Pageable pageable);

    /**
     * Finds pending outbox events excluding actively backed-off event IDs to prevent head-of-line starvation.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints({
            @QueryHint(name = "jakarta.persistence.lock.timeout", value = "-2")
    })
    @Query("SELECT o FROM OutboxEvent o WHERE o.deliveredAt IS NULL AND o.eventId NOT IN :excludedIds ORDER BY o.createdAt ASC")
    List<OutboxEvent> findPendingEventsExcluding(@Param("excludedIds") Collection<UUID> excludedIds, Pageable pageable);
}

