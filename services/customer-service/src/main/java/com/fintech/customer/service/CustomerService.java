package com.fintech.customer.service;

import com.fintech.customer.domain.AccountKind;
import com.fintech.customer.domain.AccountStatus;
import com.fintech.customer.domain.Customer;
import com.fintech.customer.domain.KycStatus;
import com.fintech.customer.dto.AccountStatusChangedEvent;
import com.fintech.customer.dto.AgentResponse;
import com.fintech.customer.dto.CustomerProfileResponse;
import com.fintech.customer.dto.CustomerProfileUpdatedEvent;
import com.fintech.customer.dto.ReceiverLookupRequest;
import com.fintech.customer.dto.ReceiverLookupResponse;
import com.fintech.customer.dto.ReceiverLookedUpEvent;
import com.fintech.customer.dto.UpdateProfileRequest;
import com.fintech.customer.dto.UpdateStatusRequest;
import com.fintech.customer.dto.UserRegisteredEvent;
import com.fintech.customer.repository.CustomerRepository;
import com.fintech.platform.correlation.CorrelationContext;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.outbox.EventEnvelope;
import com.fintech.platform.outbox.OutboxService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

@Service
public class CustomerService {

    private static final Logger log = LoggerFactory.getLogger(CustomerService.class);

    private final CustomerRepository customerRepository;
    private final OutboxService outboxService;

    public CustomerService(CustomerRepository customerRepository, OutboxService outboxService) {
        this.customerRepository = customerRepository;
        this.outboxService = outboxService;
    }

    @Transactional(readOnly = true)
    public CustomerProfileResponse getProfile(UUID userId) {
        Customer customer = customerRepository.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.NOT_FOUND, "Customer profile not found for ID: " + userId));
        return CustomerProfileResponse.from(customer);
    }

    @Transactional
    public CustomerProfileResponse updateProfile(UUID userId, UpdateProfileRequest request) {
        Customer customer = customerRepository.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.NOT_FOUND, "Customer profile not found for ID: " + userId));

        customer.setDisplayName(request.displayName().trim());
        Customer saved = customerRepository.save(customer);

        // Transactional Outbox Event for downstream services (e.g. Transaction updates wallet owner_display_name)
        CustomerProfileUpdatedEvent eventData = new CustomerProfileUpdatedEvent(
                saved.getUserId(),
                saved.getDisplayName(),
                Instant.now()
        );

        EventEnvelope<CustomerProfileUpdatedEvent> envelope = new EventEnvelope<>(
                UUID.randomUUID(),
                "CustomerProfileUpdated",
                Instant.now(),
                CorrelationContext.getCorrelationId(),
                new EventEnvelope.Actor(userId, "CUSTOMER"),
                new EventEnvelope.Resource("CUSTOMER", saved.getUserId()),
                eventData
        );
        outboxService.enqueue(envelope);

        log.info("Updated display name for user {} to '{}'", userId, saved.getDisplayName());
        return CustomerProfileResponse.from(saved);
    }

    @Transactional
    public ReceiverLookupResponse lookupReceiver(UUID callerId, ReceiverLookupRequest request) {
        String identifier = request.identifier().trim();
        Customer receiver = customerRepository.findByIdentifier(identifier)
                .orElseThrow(() -> new BusinessException(ErrorCode.RECEIVER_NOT_FOUND, "Target receiver not found"));

        // Rule 1: Caller cannot transfer to themselves
        if (callerId != null && receiver.getUserId().equals(callerId)) {
            log.warn("Self-lookup attempt by user {}", callerId);
            throw new BusinessException(ErrorCode.RECEIVER_NOT_FOUND, "Self-transfer is not permitted");
        }

        // Rule 2: Cannot send peer-to-peer transfers to cash agents
        if (receiver.getAccountKind() == AccountKind.AGENT) {
            log.warn("Lookup attempted for Cash Agent {} via peer-to-peer endpoint", receiver.getUserId());
            throw new BusinessException(ErrorCode.RECEIVER_NOT_FOUND, "Agent accounts cannot receive peer-to-peer transfers");
        }

        // Rule 3: Account must be active
        if (receiver.getAccountStatus() != AccountStatus.ACTIVE) {
            log.warn("Lookup attempted for inactive receiver account {}", receiver.getUserId());
            throw new BusinessException(ErrorCode.RECEIVER_NOT_FOUND, "Target receiver account is not active");
        }

        String rawName = (receiver.getDisplayName() != null && !receiver.getDisplayName().isBlank())
                ? receiver.getDisplayName()
                : receiver.getUsername();
        String maskedName = maskName(rawName);

        // Emit audit event via transactional outbox
        ReceiverLookedUpEvent auditData = new ReceiverLookedUpEvent(
                callerId,
                receiver.getUserId(),
                identifier,
                Instant.now()
        );

        EventEnvelope<ReceiverLookedUpEvent> envelope = new EventEnvelope<>(
                UUID.randomUUID(),
                "ReceiverLookedUp",
                Instant.now(),
                CorrelationContext.getCorrelationId(),
                new EventEnvelope.Actor(callerId, "CUSTOMER"),
                new EventEnvelope.Resource("CUSTOMER", receiver.getUserId()),
                auditData
        );
        outboxService.enqueue(envelope);

        return new ReceiverLookupResponse(receiver.getUserId(), maskedName);
    }

    @Transactional(readOnly = true)
    public List<AgentResponse> listActiveAgents() {
        return customerRepository.findByAccountKindAndAccountStatus(AccountKind.AGENT, AccountStatus.ACTIVE)
                .stream()
                .map(AgentResponse::from)
                .toList();
    }

    @Transactional(readOnly = true)
    public Page<CustomerProfileResponse> listCustomers(String search, Pageable pageable) {
        if (search == null || search.isBlank()) {
            return customerRepository.findAll(pageable).map(CustomerProfileResponse::from);
        }
        String cleanSearch = search.trim();
        return customerRepository.findByEmailContainingIgnoreCaseOrUsernameContainingIgnoreCaseOrDisplayNameContainingIgnoreCase(
                cleanSearch, cleanSearch, cleanSearch, pageable
        ).map(CustomerProfileResponse::from);
    }

    @Transactional
    public CustomerProfileResponse updateStatus(UUID adminId, UUID targetCustomerId, UpdateStatusRequest request) {
        Customer customer = customerRepository.findById(targetCustomerId)
                .orElseThrow(() -> new BusinessException(ErrorCode.NOT_FOUND, "Customer not found for ID: " + targetCustomerId));

        AccountStatus previousStatus = customer.getAccountStatus();
        if (previousStatus == request.status()) {
            return CustomerProfileResponse.from(customer);
        }

        customer.setAccountStatus(request.status());
        Customer saved = customerRepository.save(customer);

        // Transactional Outbox Event for downstream services (Transaction, Auth, Audit, Notification)
        AccountStatusChangedEvent eventData = new AccountStatusChangedEvent(
                saved.getUserId(),
                previousStatus,
                saved.getAccountStatus(),
                request.reason(),
                Instant.now()
        );

        EventEnvelope<AccountStatusChangedEvent> envelope = new EventEnvelope<>(
                UUID.randomUUID(),
                "AccountStatusChanged",
                Instant.now(),
                CorrelationContext.getCorrelationId(),
                new EventEnvelope.Actor(adminId, "ADMIN"),
                new EventEnvelope.Resource("CUSTOMER", saved.getUserId()),
                eventData
        );
        outboxService.enqueue(envelope);

        log.info("Admin {} changed customer {} status from {} to {}", adminId, targetCustomerId, previousStatus, saved.getAccountStatus());
        return CustomerProfileResponse.from(saved);
    }

    @Transactional
    public void provisionCustomer(UserRegisteredEvent event) {
        if (customerRepository.existsById(event.userId())) {
            log.info("Customer profile for user {} already exists, ignoring duplicate event", event.userId());
            return;
        }

        AccountKind kind = AccountKind.PERSONAL;
        if ("AGENT".equalsIgnoreCase(event.role()) || "AGENT".equalsIgnoreCase(event.accountKind())) {
            kind = AccountKind.AGENT;
        } else if ("MERCHANT".equalsIgnoreCase(event.accountKind())) {
            kind = AccountKind.MERCHANT;
        }

        String displayName = (event.displayName() != null && !event.displayName().isBlank())
                ? event.displayName()
                : event.username();

        Customer customer = new Customer(
                event.userId(),
                displayName,
                event.email(),
                event.username(),
                event.phone(),
                KycStatus.PENDING,
                AccountStatus.ACTIVE,
                kind
        );

        customerRepository.save(customer);
        log.info("Provisioned customer profile for user {} with kind {}", event.userId(), kind);
    }

    /**
     * Masks names according to Section 12.5:
     * First letter + asterisks for each word (e.g. "John Doe" -> "J*** D**").
     */
    public static String maskName(String fullName) {
        if (fullName == null || fullName.isBlank()) {
            return "***";
        }
        String[] words = fullName.trim().split("\\s+");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < words.length; i++) {
            String word = words[i];
            if (word.length() <= 1) {
                sb.append(word);
            } else {
                sb.append(word.charAt(0)).append("*".repeat(word.length() - 1));
            }
            if (i < words.length - 1) {
                sb.append(" ");
            }
        }
        return sb.toString();
    }
}

