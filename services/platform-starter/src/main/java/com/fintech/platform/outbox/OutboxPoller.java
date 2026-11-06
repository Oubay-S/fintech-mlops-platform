package com.fintech.platform.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;

/**
 * Scheduled background worker that polls the outbox table and delivers pending events.
 *
 * Interval: every 1 second (configurable via app.outbox.poller.fixed-delay-ms)
 * Batch size: 100 events
 * Concurrency: Multi-replica safe using SKIP LOCKED on query
 */
@Component
public class OutboxPoller {

    private static final Logger log = LoggerFactory.getLogger(OutboxPoller.class);
    private static final int BATCH_SIZE = 100;

    private final OutboxRepository outboxRepository;
    private final OutboxPublisher outboxPublisher;

    public OutboxPoller(OutboxRepository outboxRepository, OutboxPublisher outboxPublisher) {
        this.outboxRepository = outboxRepository;
        this.outboxPublisher = outboxPublisher;
    }

    @Scheduled(fixedDelayString = "${app.outbox.poller.fixed-delay-ms:1000}")
    @Transactional
    public void pollAndPublish() {
        List<OutboxEvent> pending = outboxRepository.findPendingEvents(PageRequest.of(0, BATCH_SIZE));
        if (pending.isEmpty()) {
            return;
        }

        log.debug("Found {} pending outbox event(s) to publish", pending.size());

        for (OutboxEvent event : pending) {
            try {
                outboxPublisher.publish(event);
                event.setDeliveredAt(Instant.now());
                log.debug("Successfully delivered outbox event [{}]", event.getEventId());
            } catch (Exception ex) {
                event.setAttempts(event.getAttempts() + 1);
                log.warn("Failed to deliver outbox event [{}], attempt count: {}. Error: {}",
                        event.getEventId(), event.getAttempts(), ex.getMessage());
            }
        }

        outboxRepository.saveAll(pending);
    }
}

