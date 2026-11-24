package com.fintech.customer.dto;

import com.fintech.customer.domain.AccountKind;
import com.fintech.customer.domain.AccountStatus;
import com.fintech.customer.domain.Customer;
import com.fintech.customer.domain.KycStatus;

import java.time.Instant;
import java.util.UUID;

public record CustomerProfileResponse(
        UUID userId,
        String displayName,
        String email,
        String username,
        String phone,
        KycStatus kycStatus,
        AccountStatus accountStatus,
        AccountKind accountKind,
        Instant createdAt,
        Instant updatedAt
) {
    public static CustomerProfileResponse from(Customer customer) {
        return new CustomerProfileResponse(
                customer.getUserId(),
                customer.getDisplayName(),
                customer.getEmail(),
                customer.getUsername(),
                customer.getPhone(),
                customer.getKycStatus(),
                customer.getAccountStatus(),
                customer.getAccountKind(),
                customer.getCreatedAt(),
                customer.getUpdatedAt()
        );
    }
}

