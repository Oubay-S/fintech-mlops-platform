package com.fintech.customer.repository;

import com.fintech.customer.domain.AccountKind;
import com.fintech.customer.domain.AccountStatus;
import com.fintech.customer.domain.Customer;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface CustomerRepository extends JpaRepository<Customer, UUID> {

    @Query("SELECT c FROM Customer c WHERE LOWER(c.email) = LOWER(:identifier) " +
           "OR LOWER(c.username) = LOWER(:identifier) " +
           "OR c.phone = :identifier")
    Optional<Customer> findByIdentifier(@Param("identifier") String identifier);

    Optional<Customer> findByEmailIgnoreCase(String email);

    Optional<Customer> findByUsernameIgnoreCase(String username);

    List<Customer> findByAccountKindAndAccountStatus(AccountKind accountKind, AccountStatus accountStatus);

    Page<Customer> findByEmailContainingIgnoreCaseOrUsernameContainingIgnoreCaseOrDisplayNameContainingIgnoreCase(
            String email, String username, String displayName, Pageable pageable);
}

