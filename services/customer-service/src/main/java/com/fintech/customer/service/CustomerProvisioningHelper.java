package com.fintech.customer.service;

import com.fintech.customer.domain.Customer;
import com.fintech.customer.repository.CustomerRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Isolated helper for customer provisioning.
 *
 * <p>The save is executed in its own {@code REQUIRES_NEW} transaction so that a concurrent
 * duplicate insert (DataIntegrityViolationException) rolls back <em>only this inner
 * transaction</em> and never poisons the caller's transaction with a rollback-only flag.
 * Without this isolation the outer {@code @Transactional} would be marked rollback-only
 * before the catch block fires, causing an {@code UnexpectedRollbackException} and
 * triggering infinite message-listener retries.
 */
@Component
public class CustomerProvisioningHelper {

    private static final Logger log = LoggerFactory.getLogger(CustomerProvisioningHelper.class);

    private final CustomerRepository customerRepository;

    public CustomerProvisioningHelper(CustomerRepository customerRepository) {
        this.customerRepository = customerRepository;
    }

    /**
     * Attempts to insert {@code customer} in a brand-new transaction.
     * Returns {@code true} if the row was created, {@code false} if a concurrent
     * duplicate was already present (constraint violation silently ignored).
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean saveIfAbsent(Customer customer) {
        try {
            customerRepository.saveAndFlush(customer);
            return true;
        } catch (DataIntegrityViolationException ex) {
            log.warn("Customer profile for user {} (email={}) already exists (duplicate key constraint), ignoring duplicate",
                    customer.getUserId(), customer.getEmail());
            return false;
        }
    }
}
