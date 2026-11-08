package com.fintech.platform.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Scheduled background worker that polls the outbox table and delivers pending events.
 *
 * Interval: every 1 second (configurable via app.outbox.poller.fixed-delay-ms)
 * Batch size: 100 events
 * Concurrency: Multi-replica safe using SKIP LOCKED on query
 * Retries: Exponential backoff on failure (2s, 4s, 8s... up to 300s max)
 */
@Component
public class OutboxPoller {

    private static final Logger log = LoggerFactory.getLogger(OutboxPoller.class);
    private static final int BATCH_SIZE = 100;

    private final OutboxRepository outboxRepository;
    private final OutboxPublisher outboxPublisher;
    private final Map<UUID, Instant> retrySchedule = new ConcurrentHashMap<>();

    public OutboxPoller(OutboxRepository outboxRepository, OutboxPublisher outboxPublisher) {
        this.outboxRepository = outboxRepository;
        this.outboxPublisher = outboxPublisher;
    }

    @Scheduled(fixedDelayString = "${app.outbox.poller.fixed-delay-ms:1000}")
    @Transactional
    public void pollAndPublish() {
        // Evict expired backoff intervals
        Instant now = Instant.now();
        retrySchedule.entrySet().removeIf(entry -> now.isAfter(entry.getValue()));

        // Query eligible rows: exclude backed-off IDs to prevent head-of-line starvation
        List<OutboxEvent> pending;
        if (retrySchedule.isEmpty()) {
            pending = outboxRepository.findPendingEvents(PageRequest.of(0, BATCH_SIZE));
        } else {
            pending = outboxRepository.findPendingEventsExcluding(retrySchedule.keySet(), PageRequest.of(0, BATCH_SIZE));
        }

        if (pending.isEmpty()) {
            return;
        }

        log.debug("Found {} eligible pending outbox event(s) to publish", pending.size());

        for (OutboxEvent event : pending) {
            try {
                outboxPublisher.publish(event);
                event.setDeliveredAt(Instant.now());
                retrySchedule.remove(event.getEventId());
                log.debug("Successfully delivered outbox event [{}]", event.getEventId());
            } catch (Exception ex) {
                event.setAttempts(event.getAttempts() + 1);
                long backoffSeconds = (long) Math.min(Math.pow(2, event.getAttempts()), 300);
                retrySchedule.put(event.getEventId(), Instant.now().plusSeconds(backoffSeconds));
                log.warn("Failed to deliver outbox event [{}], attempt count: {}. Retrying in {}s. Error: {}",
                        event.getEventId(), event.getAttempts(), backoffSeconds, ex.getMessage());
            }
        }

        outboxRepository.saveAll(pending);
    }
}

