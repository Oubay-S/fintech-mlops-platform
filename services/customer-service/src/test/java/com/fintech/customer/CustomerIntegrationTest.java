package com.fintech.customer;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fintech.customer.domain.AccountKind;
import com.fintech.customer.domain.AccountStatus;
import com.fintech.customer.domain.Customer;
import com.fintech.customer.domain.KycStatus;
import com.fintech.customer.dto.ReceiverLookupRequest;
import com.fintech.customer.dto.UpdateProfileRequest;
import com.fintech.customer.dto.UpdateStatusRequest;
import com.fintech.customer.repository.CustomerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.http.MediaType;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class CustomerIntegrationTest {

    @TestConfiguration
    static class TestSecurityConfig {
        @Bean
        public JwtDecoder jwtDecoder() {
            return mock(JwtDecoder.class);
        }
    }

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private CustomerRepository customerRepository;

    private UUID userAliceId;
    private UUID userBobId;
    private UUID agentId;
    private UUID adminId;

    private static SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor customerJwt(UUID userId) {
        return jwt()
                .jwt(j -> j.subject(userId.toString()).claim("role", "CUSTOMER"))
                .authorities(new SimpleGrantedAuthority("ROLE_CUSTOMER"));
    }

    private static SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor adminJwt(UUID adminId) {
        return jwt()
                .jwt(j -> j.subject(adminId.toString()).claim("role", "ADMIN"))
                .authorities(new SimpleGrantedAuthority("ROLE_ADMIN"));
    }

    private static SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor serviceJwt(String serviceName) {
        return jwt()
                .jwt(j -> j.subject(serviceName).claim("role", "SERVICE"))
                .authorities(new SimpleGrantedAuthority("ROLE_SERVICE"));
    }

    @BeforeEach
    void setUp() {
        customerRepository.deleteAll();

        userAliceId = UUID.randomUUID();
        userBobId = UUID.randomUUID();
        agentId = UUID.randomUUID();
        adminId = UUID.randomUUID();

        Customer alice = new Customer(
                userAliceId,
                "Alice Wonderland",
                "alice@example.com",
                "alice",
                "+1234567890",
                KycStatus.VERIFIED,
                AccountStatus.ACTIVE,
                AccountKind.PERSONAL
        );

        Customer bob = new Customer(
                userBobId,
                "Bob Builder",
                "bob@example.com",
                "bob",
                "+1987654321",
                KycStatus.PENDING,
                AccountStatus.ACTIVE,
                AccountKind.PERSONAL
        );

        Customer agent = new Customer(
                agentId,
                "Cash Agent Casher",
                "agent@example.com",
                "casher",
                "+1122334455",
                KycStatus.VERIFIED,
                AccountStatus.ACTIVE,
                AccountKind.AGENT
        );

        customerRepository.save(alice);
        customerRepository.save(bob);
        customerRepository.save(agent);
    }

    @Test
    @DisplayName("GET /customers/me returns current user's profile")
    void testGetOwnProfile() throws Exception {
        mockMvc.perform(get("/customers/me")
                        .with(customerJwt(userAliceId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(userAliceId.toString()))
                .andExpect(jsonPath("$.email").value("alice@example.com"))
                .andExpect(jsonPath("$.displayName").value("Alice Wonderland"));
    }

    @Test
    @DisplayName("PUT /customers/me updates display name and returns 200")
    void testUpdateOwnProfile() throws Exception {
        UpdateProfileRequest request = new UpdateProfileRequest("Alice In Wonderland");

        mockMvc.perform(put("/customers/me")
                        .with(customerJwt(userAliceId))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.displayName").value("Alice In Wonderland"));

        Customer updated = customerRepository.findById(userAliceId).orElseThrow();
        assertThat(updated.getDisplayName()).isEqualTo("Alice In Wonderland");
    }

    @Test
    @DisplayName("POST /customers/lookup returns masked name for recipient")
    void testReceiverLookupSuccess() throws Exception {
        ReceiverLookupRequest request = new ReceiverLookupRequest("bob@example.com");

        mockMvc.perform(post("/customers/lookup")
                        .with(customerJwt(userAliceId))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.receiverId").value(userBobId.toString()))
                .andExpect(jsonPath("$.maskedName").value("B** B******"));
    }

    @Test
    @DisplayName("POST /customers/lookup fails with 404 RECEIVER_NOT_FOUND on self-lookup")
    void testReceiverLookupSelfFails() throws Exception {
        ReceiverLookupRequest request = new ReceiverLookupRequest("alice@example.com");

        mockMvc.perform(post("/customers/lookup")
                        .with(customerJwt(userAliceId))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("RECEIVER_NOT_FOUND"));
    }

    @Test
    @DisplayName("POST /customers/lookup fails with 404 RECEIVER_NOT_FOUND for Cash Agent")
    void testReceiverLookupAgentFails() throws Exception {
        ReceiverLookupRequest request = new ReceiverLookupRequest("casher");

        mockMvc.perform(post("/customers/lookup")
                        .with(customerJwt(userAliceId))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("RECEIVER_NOT_FOUND"));
    }

    @Test
    @DisplayName("GET /customers/agents lists active cash agents")
    void testListActiveAgents() throws Exception {
        mockMvc.perform(get("/customers/agents")
                        .with(customerJwt(userAliceId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].username").value("casher"));
    }

    @Test
    @DisplayName("Admin customer listing: ADMIN allowed, CUSTOMER forbidden (403)")
    void testAdminCustomerListingSecurity() throws Exception {
        // Customer forbidden
        mockMvc.perform(get("/customers")
                        .with(customerJwt(userAliceId)))
                .andExpect(status().isForbidden());

        // Admin allowed
        mockMvc.perform(get("/customers")
                        .with(adminJwt(adminId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content.length()").value(3));
    }

    @Test
    @DisplayName("PATCH /customers/{id}/status changes account status by ADMIN")
    void testAdminUpdateStatus() throws Exception {
        UpdateStatusRequest request = new UpdateStatusRequest(AccountStatus.BLOCKED, "Suspected fraud");

        mockMvc.perform(patch("/customers/{id}/status", userBobId)
                        .with(adminJwt(adminId))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accountStatus").value("BLOCKED"));

        Customer bob = customerRepository.findById(userBobId).orElseThrow();
        assertThat(bob.getAccountStatus()).isEqualTo(AccountStatus.BLOCKED);
    }

    @Test
    @DisplayName("GET /internal/customers/{id} requires ROLE_SERVICE authority")
    void testInternalCustomerSnapshot() throws Exception {
        // Customer forbidden
        mockMvc.perform(get("/internal/customers/{id}", userAliceId)
                        .with(customerJwt(userAliceId)))
                .andExpect(status().isForbidden());

        // Service token allowed
        mockMvc.perform(get("/internal/customers/{id}", userAliceId)
                        .with(serviceJwt("risk-service")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(userAliceId.toString()))
                .andExpect(jsonPath("$.email").value("alice@example.com"));
    }

    @Test
    @DisplayName("POST /internal/events provisions user registered event (HTTP fallback)")
    void testInternalHttpEventIntake() throws Exception {
        UUID newUserId = UUID.randomUUID();
        String jsonEvent = """
                {
                  "eventId": "%s",
                  "type": "auth.user.registered",
                  "occurredAt": "%s",
                  "correlationId": "%s",
                  "actor": { "id": "%s", "role": "CUSTOMER" },
                  "resource": { "type": "USER", "id": "%s" },
                  "data": {
                    "userId": "%s",
                    "email": "david@example.com",
                    "username": "davidd",
                    "phone": "+212611223344",
                    "role": "CUSTOMER",
                    "accountKind": "PERSONAL",
                    "displayName": "David Miller",
                    "occurredAt": "%s"
                  }
                }
                """.formatted(UUID.randomUUID(), Instant.now(), UUID.randomUUID(), newUserId, newUserId, newUserId, Instant.now());

        mockMvc.perform(post("/internal/events")
                        .with(serviceJwt("auth-service"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(jsonEvent))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("PROCESSED"));

        Customer david = customerRepository.findById(newUserId).orElseThrow();
        assertThat(david.getEmail()).isEqualTo("david@example.com");
        assertThat(david.getDisplayName()).isEqualTo("David Miller");
        assertThat(david.getAccountKind()).isEqualTo(AccountKind.PERSONAL);
    }

    @Test
    @DisplayName("GET /customers/me rejects non-CUSTOMER roles (e.g. SERVICE tokens) with 403")
    void testGetOwnProfileRejectsServiceRole() throws Exception {
        mockMvc.perform(get("/customers/me")
                        .with(serviceJwt("risk-service")))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("POST /internal/events rejects malformed event with 400")
    void testInternalHttpEventIntakeMalformed() throws Exception {
        String invalidEvent = """
                {
                  "type": "auth.user.registered",
                  "data": null
                }
                """;

        mockMvc.perform(post("/internal/events")
                        .with(serviceJwt("auth-service"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(invalidEvent))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("PUT /customers/me rejects display name that trims below minimum length")
    void testUpdateOwnProfileTrimmedTooShortFails() throws Exception {
        UpdateProfileRequest request = new UpdateProfileRequest(" A ");

        mockMvc.perform(put("/customers/me")
                        .with(customerJwt(userAliceId))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }
}
