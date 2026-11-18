package com.fintech.auth.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fintech.auth.dto.AccountStatusChangedEvent;
import com.fintech.auth.dto.ServiceTokenRequest;
import com.fintech.auth.dto.ServiceTokenResponse;
import com.fintech.auth.service.AuthEventListener;
import com.fintech.auth.service.AuthService;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/internal/auth")
public class InternalAuthController {

    private static final Logger log = LoggerFactory.getLogger(InternalAuthController.class);

    private final AuthService authService;
    private final AuthEventListener authEventListener;

    public InternalAuthController(AuthService authService, AuthEventListener authEventListener) {
        this.authService = authService;
        this.authEventListener = authEventListener;
    }

    @PostMapping("/service-token")
    public ResponseEntity<ServiceTokenResponse> getServiceToken(@Valid @RequestBody ServiceTokenRequest request) {
        ServiceTokenResponse response = authService.issueServiceToken(request);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/events")
    @Operation(summary = "HTTP Outbox Event Intake for Auth", description = "Fallback delivery endpoint for outbox events (Option C hybrid messaging)")
    public ResponseEntity<Map<String, String>> receiveInternalEvent(@RequestBody JsonNode envelopeNode) {
        String eventType = envelopeNode.path("type").asText();
        log.info("Received internal HTTP event in auth-service of type: {}", eventType);

        if ("customer.account.status-changed".equalsIgnoreCase(eventType)) {
            JsonNode dataNode = envelopeNode.path("data");
            AccountStatusChangedEvent event = authEventListener.parseAccountStatusChangedEvent(dataNode);
            if (event != null && event.userId() != null) {
                authService.handleAccountStatusChanged(event.userId(), event.newStatus(), event.reason());
            } else {
                throw new BusinessException(ErrorCode.VALIDATION_FAILED, "Invalid or missing payload data for customer.account.status-changed event");
            }
        }

        return ResponseEntity.ok(Map.of("status", "PROCESSED", "type", eventType));
    }
}
