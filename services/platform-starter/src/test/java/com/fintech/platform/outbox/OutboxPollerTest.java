package com.fintech.platform.outbox;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Pageable;

import java.util.Collections;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class OutboxPollerTest {

    @Mock
    private OutboxRepository outboxRepository;

    @Mock
    private OutboxPublisher outboxPublisher;

    @InjectMocks
    private OutboxPoller outboxPoller;

    @Test
    void shouldDoNothingWhenNoPendingEvents() {
        when(outboxRepository.findPendingEvents(any(Pageable.class))).thenReturn(Collections.emptyList());

        outboxPoller.pollAndPublish();

        verifyNoInteractions(outboxPublisher);
        verify(outboxRepository, never()).saveAll(any());
    }

    @Test
    void shouldPublishPendingEventAndMarkDelivered() throws Exception {
        OutboxEvent event = new OutboxEvent(UUID.randomUUID(), "TransferCompleted", "{\"amount\": 100.00}");
        when(outboxRepository.findPendingEvents(any(Pageable.class))).thenReturn(List.of(event));

        outboxPoller.pollAndPublish();

        verify(outboxPublisher, times(1)).publish(event);
        assertThat(event.getDeliveredAt()).isNotNull();
        assertThat(event.getAttempts()).isEqualTo(0);
        verify(outboxRepository, times(1)).saveAll(List.of(event));
    }

    @Test
    void shouldIncrementAttemptsWhenPublishingFails() throws Exception {
        OutboxEvent event = new OutboxEvent(UUID.randomUUID(), "TransferCompleted", "{\"amount\": 100.00}");
        when(outboxRepository.findPendingEvents(any(Pageable.class))).thenReturn(List.of(event));
        doThrow(new RuntimeException("Broker unreachable")).when(outboxPublisher).publish(event);

        outboxPoller.pollAndPublish();

        verify(outboxPublisher, times(1)).publish(event);
        assertThat(event.getDeliveredAt()).isNull();
        assertThat(event.getAttempts()).isEqualTo(1);
        verify(outboxRepository, times(1)).saveAll(List.of(event));
    }
}

