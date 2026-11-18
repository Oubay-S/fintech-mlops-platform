package com.fintech.customer.dto;

import com.fintech.customer.domain.Customer;

import java.util.UUID;

public record AgentResponse(
        UUID userId,
        String displayName,
        String username,
        String phone
) {
    public static AgentResponse from(Customer customer) {
        return new AgentResponse(
                customer.getUserId(),
                customer.getDisplayName(),
                customer.getUsername(),
                customer.getPhone()
        );
    }
}

