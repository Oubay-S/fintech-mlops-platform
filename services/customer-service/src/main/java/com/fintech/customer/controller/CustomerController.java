package com.fintech.customer.controller;

import com.fintech.customer.dto.AgentResponse;
import com.fintech.customer.dto.CustomerProfileResponse;
import com.fintech.customer.dto.ReceiverLookupRequest;
import com.fintech.customer.dto.ReceiverLookupResponse;
import com.fintech.customer.dto.UpdateProfileRequest;
import com.fintech.customer.service.CustomerService;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.security.SecurityUtils;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/customers")
@Tag(name = "Customer Operations", description = "Customer self-service profiles, receiver lookup, and cash agent listing")
public class CustomerController {

    private final CustomerService customerService;

    public CustomerController(CustomerService customerService) {
        this.customerService = customerService;
    }

    @GetMapping("/me")
    @PreAuthorize("hasRole('CUSTOMER')")
    @Operation(summary = "Get own profile", description = "Retrieves the currently authenticated customer's profile")
    public ResponseEntity<CustomerProfileResponse> getMyProfile() {
        UUID currentUserId = SecurityUtils.getAuthenticatedUserId();
        if (currentUserId == null) {
            throw new BusinessException(ErrorCode.UNAUTHENTICATED, "No authenticated user in context");
        }
        return ResponseEntity.ok(customerService.getProfile(currentUserId));
    }

    @PutMapping("/me")
    @PreAuthorize("hasRole('CUSTOMER')")
    @Operation(summary = "Update display name", description = "Updates own display name and emits CustomerProfileUpdated outbox event")
    public ResponseEntity<CustomerProfileResponse> updateMyProfile(@Valid @RequestBody UpdateProfileRequest request) {
        UUID currentUserId = SecurityUtils.getAuthenticatedUserId();
        if (currentUserId == null) {
            throw new BusinessException(ErrorCode.UNAUTHENTICATED, "No authenticated user in context");
        }
        return ResponseEntity.ok(customerService.updateProfile(currentUserId, request));
    }

    @PostMapping("/lookup")
    @PreAuthorize("hasRole('CUSTOMER')")
    @Operation(summary = "Lookup recipient", description = "Looks up recipient by email/username/phone and returns masked name without disclosing PII")
    public ResponseEntity<ReceiverLookupResponse> lookupReceiver(@Valid @RequestBody ReceiverLookupRequest request) {
        UUID currentUserId = SecurityUtils.getAuthenticatedUserId();
        return ResponseEntity.ok(customerService.lookupReceiver(currentUserId, request));
    }

    @GetMapping("/agents")
    @PreAuthorize("hasRole('CUSTOMER')")
    @Operation(summary = "List active cash agents", description = "Returns active cash agents available for cash withdrawals")
    public ResponseEntity<List<AgentResponse>> listAgents() {
        return ResponseEntity.ok(customerService.listActiveAgents());
    }
}

