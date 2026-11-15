package com.fintech.customer.controller;

import com.fintech.customer.dto.CustomerProfileResponse;
import com.fintech.customer.dto.UpdateStatusRequest;
import com.fintech.customer.service.CustomerService;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.security.SecurityUtils;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/customers")
@PreAuthorize("hasRole('ADMIN')")
@Tag(name = "Customer Administration", description = "Back-office management of customer accounts and statuses")
public class AdminCustomerController {

    private final CustomerService customerService;

    public AdminCustomerController(CustomerService customerService) {
        this.customerService = customerService;
    }

    @GetMapping
    @Operation(summary = "Search & list customers", description = "Admin paginated query across customer accounts with optional search string")
    public ResponseEntity<Page<CustomerProfileResponse>> listCustomers(
            @RequestParam(required = false) String search,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "createdAt") String sortBy,
            @RequestParam(defaultValue = "DESC") String direction
    ) {
        Sort.Direction sortDirection = "ASC".equalsIgnoreCase(direction) ? Sort.Direction.ASC : Sort.Direction.DESC;
        PageRequest pageRequest = PageRequest.of(page, size, Sort.by(sortDirection, sortBy));
        return ResponseEntity.ok(customerService.listCustomers(search, pageRequest));
    }

    @PatchMapping("/{id}/status")
    @Operation(summary = "Update account status", description = "Blocks or unblocks a customer and emits AccountStatusChanged outbox event")
    public ResponseEntity<CustomerProfileResponse> updateStatus(
            @PathVariable UUID id,
            @Valid @RequestBody UpdateStatusRequest request
    ) {
        UUID adminId = SecurityUtils.getAuthenticatedUserId();
        if (adminId == null) {
            throw new BusinessException(ErrorCode.UNAUTHENTICATED, "No admin identity in security context");
        }
        return ResponseEntity.ok(customerService.updateStatus(adminId, id, request));
    }
}

