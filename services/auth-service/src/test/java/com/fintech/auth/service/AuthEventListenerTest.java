package com.fintech.auth.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.UUID;

import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthEventListenerTest {

    @Mock
    private AuthService authService;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private AuthEventListener authEventListener;

    private UUID userId;

    @BeforeEach
    void setUp() {
        userId = UUID.randomUUID();
    }

    @Test
    @DisplayName("onMessage processes customer.account.status-changed and disables user when BLOCKED")
    void testOnMessageAccountBlocked() {
        String jsonPayload = """
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "type": "customer.account.status-changed",
                    "data": {
                        "userId": "%s",
                        "previousStatus": "ACTIVE",
                        "newStatus": "BLOCKED",
                        "reason": "Suspected AML breach"
                    }
                }
                """.formatted(userId);

        authEventListener.onMessage(jsonPayload);

        verify(authService, times(1)).handleAccountStatusChanged(userId, "BLOCKED", "Suspected AML breach");
    }

    @Test
    @DisplayName("onMessage processes customer.account.status-changed and enables user when ACTIVE")
    void testOnMessageAccountActive() {
        String jsonPayload = """
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "type": "customer.account.status-changed",
                    "data": {
                        "userId": "%s",
                        "previousStatus": "BLOCKED",
                        "newStatus": "ACTIVE",
                        "reason": "False alarm"
                    }
                }
                """.formatted(userId);

        authEventListener.onMessage(jsonPayload);

        verify(authService, times(1)).handleAccountStatusChanged(userId, "ACTIVE", "False alarm");
    }

    @Test
    @DisplayName("onMessage ignores unknown event types without error")
    void testOnMessageIgnoresUnknownEvents() {
        String jsonPayload = """
                {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "type": "customer.profile.updated",
                    "data": {}
                }
                """;

        authEventListener.onMessage(jsonPayload);

        verify(authService, never()).handleAccountStatusChanged(any(), any(), any());
    }
}
