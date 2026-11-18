package com.fintech.customer.service;

import com.fintech.customer.domain.AccountKind;
import com.fintech.customer.domain.AccountStatus;
import com.fintech.customer.domain.Customer;
import com.fintech.customer.domain.KycStatus;
import com.fintech.customer.repository.CustomerRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CustomerProvisioningHelperTest {

    @Mock
    private CustomerRepository customerRepository;

    @InjectMocks
    private CustomerProvisioningHelper provisioningHelper;

    @Test
    @DisplayName("saveIfAbsent returns true when repository save succeeds")
    void testSaveIfAbsentSuccess() {
        Customer customer = new Customer(
                UUID.randomUUID(),
                "John Doe",
                "john@example.com",
                "johndoe",
                "+1234567890",
                KycStatus.PENDING,
                AccountStatus.ACTIVE,
                AccountKind.PERSONAL
        );
        when(customerRepository.saveAndFlush(any(Customer.class))).thenReturn(customer);

        boolean result = provisioningHelper.saveIfAbsent(customer);

        assertThat(result).isTrue();
    }

    @Test
    @DisplayName("saveIfAbsent catches DataIntegrityViolationException and returns false")
    void testSaveIfAbsentConstraintViolation() {
        Customer customer = new Customer(
                UUID.randomUUID(),
                "John Doe",
                "john@example.com",
                "johndoe",
                "+1234567890",
                KycStatus.PENDING,
                AccountStatus.ACTIVE,
                AccountKind.PERSONAL
        );
        when(customerRepository.saveAndFlush(any(Customer.class)))
                .thenThrow(new DataIntegrityViolationException("duplicate key value violates unique constraint"));

        boolean result = provisioningHelper.saveIfAbsent(customer);

        assertThat(result).isFalse();
    }
}
