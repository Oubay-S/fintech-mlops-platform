package com.fintech.customer.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fintech.customer.dto.CustomerProfileResponse;
import com.fintech.customer.dto.UserRegisteredEvent;
import com.fintech.customer.service.CustomerEventListener;
import com.fintech.customer.service.CustomerService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/internal")
@PreAuthorize("hasAuthority('ROLE_SERVICE')")
@Tag(name = "Internal Service APIs", description = "M2M endpoints for cross-service communication (Risk snapshots, HTTP event intake)")
public class InternalCustomerController {

    private static final Logger log = LoggerFactory.getLogger(InternalCustomerController.class);

    private final CustomerService customerService;
    private final CustomerEventListener customerEventListener;

    public InternalCustomerController(CustomerService customerService, CustomerEventListener customerEventListener) {
        this.customerService = customerService;
        this.customerEventListener = customerEventListener;
    }

    @GetMapping("/customers/{id}")
    @Operation(summary = "Get full customer profile snapshot", description = "Called by Risk Service during decision evaluation for case snapshots")
    public ResponseEntity<CustomerProfileResponse> getCustomerSnapshot(@PathVariable UUID id) {
        return ResponseEntity.ok(customerService.getProfile(id));
    }

    @PostMapping("/events")
    @Operation(summary = "HTTP Outbox Event Intake", description = "Fallback delivery endpoint for outbox events (Option C hybrid messaging)")
    public ResponseEntity<Map<String, String>> receiveInternalEvent(@RequestBody JsonNode envelopeNode) {
        String eventType = envelopeNode.path("type").asText();
        log.info("Received internal HTTP event of type: {}", eventType);

        if ("auth.user.registered".equalsIgnoreCase(eventType)) {
            JsonNode dataNode = envelopeNode.path("data");
            UserRegisteredEvent event = customerEventListener.parseUserRegisteredEvent(dataNode);
            if (event != null) {
                customerService.provisionCustomer(event);
            }
        }

        return ResponseEntity.ok(Map.of("status", "PROCESSED", "type", eventType));
    }
}

