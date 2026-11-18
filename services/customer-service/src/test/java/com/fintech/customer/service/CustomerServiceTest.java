package com.fintech.customer.service;

import com.fintech.customer.domain.AccountKind;
import com.fintech.customer.domain.AccountStatus;
import com.fintech.customer.domain.Customer;
import com.fintech.customer.domain.KycStatus;
import com.fintech.customer.dto.AgentResponse;
import com.fintech.customer.dto.CustomerProfileResponse;
import com.fintech.customer.dto.ReceiverLookupRequest;
import com.fintech.customer.dto.ReceiverLookupResponse;
import com.fintech.customer.dto.ReceiverLookedUpEvent;
import com.fintech.customer.dto.UpdateProfileRequest;
import com.fintech.customer.dto.UpdateStatusRequest;
import com.fintech.customer.dto.UserRegisteredEvent;
import com.fintech.customer.repository.CustomerRepository;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.outbox.EventEnvelope;
import com.fintech.platform.outbox.OutboxService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CustomerServiceTest {

    @Mock
    private CustomerRepository customerRepository;

    @Mock
    private OutboxService outboxService;

    @Mock
    private CustomerProvisioningHelper provisioningHelper;

    @InjectMocks
    private CustomerService customerService;

    private Customer alice;
    private Customer bob;
    private Customer cashAgent;

    @BeforeEach
    void setUp() {
        alice = new Customer(
                UUID.randomUUID(),
                "Alice Wonderland",
                "alice@example.com",
                "alice",
                "+1234567890",
                KycStatus.VERIFIED,
                AccountStatus.ACTIVE,
                AccountKind.PERSONAL
        );

        bob = new Customer(
                UUID.randomUUID(),
                "Bob Builder",
                "bob@example.com",
                "bob",
                "+1987654321",
                KycStatus.PENDING,
                AccountStatus.ACTIVE,
                AccountKind.PERSONAL
        );

        cashAgent = new Customer(
                UUID.randomUUID(),
                "Agent Smith",
                "agent@example.com",
                "agent007",
                "+1122334455",
                KycStatus.VERIFIED,
                AccountStatus.ACTIVE,
                AccountKind.AGENT
        );
    }

    @Test
    @DisplayName("getProfile returns profile when customer exists")
    void testGetProfileSuccess() {
        when(customerRepository.findById(alice.getUserId())).thenReturn(Optional.of(alice));

        CustomerProfileResponse response = customerService.getProfile(alice.getUserId());

        assertThat(response.userId()).isEqualTo(alice.getUserId());
        assertThat(response.email()).isEqualTo("alice@example.com");
        assertThat(response.displayName()).isEqualTo("Alice Wonderland");
    }

    @Test
    @DisplayName("getProfile throws NOT_FOUND when customer does not exist")
    void testGetProfileNotFound() {
        UUID unknownId = UUID.randomUUID();
        when(customerRepository.findById(unknownId)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> customerService.getProfile(unknownId))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.NOT_FOUND);
    }

    @Test
    @DisplayName("updateProfile updates display name and enqueues outbox event")
    void testUpdateProfileSuccess() {
        when(customerRepository.findById(alice.getUserId())).thenReturn(Optional.of(alice));
        when(customerRepository.save(any(Customer.class))).thenAnswer(invocation -> invocation.getArgument(0));

        CustomerProfileResponse response = customerService.updateProfile(
                alice.getUserId(),
                new UpdateProfileRequest("Alice In Chains")
        );

        assertThat(response.displayName()).isEqualTo("Alice In Chains");
        ArgumentCaptor<EventEnvelope> captor = ArgumentCaptor.forClass(EventEnvelope.class);
        verify(outboxService, times(1)).enqueue(captor.capture());
        assertThat(captor.getValue().getType()).isEqualTo("customer.profile.updated");
    }

    @Test
    @DisplayName("lookupReceiver successfully returns masked name for active personal customer")
    void testLookupReceiverSuccess() {
        when(customerRepository.findByIdentifier("bob@example.com")).thenReturn(Optional.of(bob));

        ReceiverLookupResponse response = customerService.lookupReceiver(
                alice.getUserId(),
                new ReceiverLookupRequest("bob@example.com")
        );

        assertThat(response.receiverId()).isEqualTo(bob.getUserId());
        // "Bob Builder" masked: B** B******
        assertThat(response.maskedName()).isEqualTo("B** B******");

        ArgumentCaptor<EventEnvelope> captor = ArgumentCaptor.forClass(EventEnvelope.class);
        verify(outboxService, times(1)).enqueue(captor.capture());
        assertThat(captor.getValue().getType()).isEqualTo("customer.receiver.lookedup");
        ReceiverLookedUpEvent event = (ReceiverLookedUpEvent) captor.getValue().getData();
        assertThat(event.identifierHash()).isNotEqualTo("bob@example.com");
        assertThat(event.identifierHash()).isEqualTo(CustomerService.sha256Hex("bob@example.com"));
    }

    @Test
    @DisplayName("lookupReceiver throws RECEIVER_NOT_FOUND when identifier matches caller (self-transfer)")
    void testLookupReceiverSelfTransferFails() {
        when(customerRepository.findByIdentifier("alice@example.com")).thenReturn(Optional.of(alice));

        assertThatThrownBy(() -> customerService.lookupReceiver(
                alice.getUserId(),
                new ReceiverLookupRequest("alice@example.com")
        )).isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.RECEIVER_NOT_FOUND);

        verify(outboxService, never()).enqueue(any());
    }

    @Test
    @DisplayName("lookupReceiver throws RECEIVER_NOT_FOUND when target is a cash agent")
    void testLookupReceiverAgentFails() {
        when(customerRepository.findByIdentifier("agent007")).thenReturn(Optional.of(cashAgent));

        assertThatThrownBy(() -> customerService.lookupReceiver(
                alice.getUserId(),
                new ReceiverLookupRequest("agent007")
        )).isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.RECEIVER_NOT_FOUND);

        verify(outboxService, never()).enqueue(any());
    }

    @Test
    @DisplayName("lookupReceiver throws RECEIVER_NOT_FOUND when target account is blocked")
    void testLookupReceiverBlockedAccountFails() {
        bob.setAccountStatus(AccountStatus.BLOCKED);
        when(customerRepository.findByIdentifier("bob@example.com")).thenReturn(Optional.of(bob));

        assertThatThrownBy(() -> customerService.lookupReceiver(
                alice.getUserId(),
                new ReceiverLookupRequest("bob@example.com")
        )).isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.RECEIVER_NOT_FOUND);

        verify(outboxService, never()).enqueue(any());
    }

    @Test
    @DisplayName("listActiveAgents returns only active cash agents")
    void testListActiveAgents() {
        when(customerRepository.findByAccountKindAndAccountStatus(AccountKind.AGENT, AccountStatus.ACTIVE))
                .thenReturn(List.of(cashAgent));

        List<AgentResponse> agents = customerService.listActiveAgents();

        assertThat(agents).hasSize(1);
        assertThat(agents.get(0).username()).isEqualTo("agent007");
    }

    @Test
    @DisplayName("updateStatus updates account status and enqueues AccountStatusChanged event")
    void testUpdateStatusSuccess() {
        UUID adminId = UUID.randomUUID();
        when(customerRepository.findById(bob.getUserId())).thenReturn(Optional.of(bob));
        when(customerRepository.save(any(Customer.class))).thenAnswer(invocation -> invocation.getArgument(0));

        CustomerProfileResponse response = customerService.updateStatus(
                adminId,
                bob.getUserId(),
                new UpdateStatusRequest(AccountStatus.BLOCKED, "Suspected AML breach")
        );

        assertThat(response.accountStatus()).isEqualTo(AccountStatus.BLOCKED);
        ArgumentCaptor<EventEnvelope> captor = ArgumentCaptor.forClass(EventEnvelope.class);
        verify(outboxService, times(1)).enqueue(captor.capture());
        assertThat(captor.getValue().getType()).isEqualTo("customer.account.status-changed");
    }

    @Test
    @DisplayName("provisionCustomer idempotently saves new customer from UserRegisteredEvent")
    void testProvisionCustomerIdempotent() {
        UUID newUserId = UUID.randomUUID();
        UserRegisteredEvent event = new UserRegisteredEvent(
                newUserId,
                "charlie@example.com",
                "charlie",
                "+1112223334",
                "CUSTOMER",
                "PERSONAL",
                "Charlie Brown",
                Instant.now()
        );

        when(customerRepository.existsById(newUserId)).thenReturn(false);
        when(provisioningHelper.saveIfAbsent(any(Customer.class))).thenReturn(true);

        customerService.provisionCustomer(event);

        ArgumentCaptor<Customer> captor = ArgumentCaptor.forClass(Customer.class);
        verify(provisioningHelper, times(1)).saveIfAbsent(captor.capture());
        Customer saved = captor.getValue();
        assertThat(saved.getUserId()).isEqualTo(newUserId);
        assertThat(saved.getEmail()).isEqualTo("charlie@example.com");
        assertThat(saved.getDisplayName()).isEqualTo("Charlie Brown");
        assertThat(saved.getAccountKind()).isEqualTo(AccountKind.PERSONAL);

        // Second invocation: should be idempotent and not call save again
        when(customerRepository.existsById(newUserId)).thenReturn(true);
        customerService.provisionCustomer(event);
        verify(provisioningHelper, times(1)).saveIfAbsent(any());
    }

    @Test
    @DisplayName("maskName correctly masks single and multi-word names")
    void testMaskName() {
        assertThat(CustomerService.maskName("John Doe")).isEqualTo("J*** D**");
        assertThat(CustomerService.maskName("A B")).isEqualTo("A B");
        assertThat(CustomerService.maskName("Alice")).isEqualTo("A****");
        assertThat(CustomerService.maskName("")).isEqualTo("***");
        assertThat(CustomerService.maskName(null)).isEqualTo("***");
    }

    @Test
    @DisplayName("sha256Hex correctly hashes normalized inputs")
    void testSha256Hex() {
        String hash1 = CustomerService.sha256Hex("Alice@Example.Com ");
        String hash2 = CustomerService.sha256Hex("alice@example.com");
        assertThat(hash1).isEqualTo(hash2);
        assertThat(hash1).hasSize(64);
        assertThat(CustomerService.sha256Hex(null)).isEmpty();
        assertThat(CustomerService.sha256Hex("  ")).isEmpty();
    }
}

