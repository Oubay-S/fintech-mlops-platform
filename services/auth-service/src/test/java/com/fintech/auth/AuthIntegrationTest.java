package com.fintech.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fintech.auth.domain.AccountKind;
import com.fintech.auth.dto.LoginRequest;
import com.fintech.auth.dto.RegisterRequest;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.cookie;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AuthIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private com.fintech.auth.security.JwtService jwtService;

    @Autowired
    private com.fintech.auth.repository.UserRepository userRepository;

    @Test
    @DisplayName("Full Auth lifecycle: JWKS, Register, Login, Refresh, Logout, and Duplicate prevention")
    void testAuthLifecycle() throws Exception {
        // 1. Verify JWKS public keys are exposed
        mockMvc.perform(get("/.well-known/jwks.json"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.keys[0].kty").value("RSA"))
                .andExpect(jsonPath("$.keys[0].alg").value("RS256"));

        // 2. Register customer
        RegisterRequest registerReq = new RegisterRequest(
                "bob@example.com",
                "bobthebuilder",
                "+212600000099",
                "Password123!",
                AccountKind.PERSONAL,
                "Bob Builder"
        );

        mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(registerReq)))
                .andExpect(status().isCreated());

        // 3. Register duplicate email returns 409 Conflict
        mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(registerReq)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("EMAIL_ALREADY_EXISTS"));

        // 4. Login customer
        LoginRequest loginReq = new LoginRequest("bobthebuilder", "Password123!");
        MvcResult loginResult = mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(loginReq)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").isNotEmpty())
                .andExpect(jsonPath("$.roles[0]").value("CUSTOMER"))
                .andExpect(cookie().exists("refresh_token"))
                .andReturn();

        Cookie refreshCookie = loginResult.getResponse().getCookie("refresh_token");
        assertThat(refreshCookie).isNotNull();

        // 5. Refresh token rotation
        MvcResult refreshResult = mockMvc.perform(post("/auth/refresh")
                        .cookie(refreshCookie))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").isNotEmpty())
                .andExpect(cookie().exists("refresh_token"))
                .andReturn();

        Cookie rotatedCookie = refreshResult.getResponse().getCookie("refresh_token");
        assertThat(rotatedCookie).isNotNull();
        assertThat(rotatedCookie.getValue()).isNotEqualTo(refreshCookie.getValue());

        // 6. Token reuse detection: presenting the already-rotated token must trigger 401 and chain revocation
        mockMvc.perform(post("/auth/refresh")
                        .cookie(refreshCookie))
                .andExpect(status().isUnauthorized());

        // The successor rotated token must now also be rejected because reuse revokes the entire user chain
        mockMvc.perform(post("/auth/refresh")
                        .cookie(rotatedCookie))
                .andExpect(status().isUnauthorized());

        // 7. Login again after chain revocation and verify logout
        MvcResult reLoginResult = mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(loginReq)))
                .andExpect(status().isOk())
                .andReturn();

        Cookie freshCookie = reLoginResult.getResponse().getCookie("refresh_token");
        assertThat(freshCookie).isNotNull();

        // 8. Logout with valid fresh token
        mockMvc.perform(post("/auth/logout")
                        .cookie(freshCookie))
                .andExpect(status().isOk())
                .andExpect(cookie().maxAge("refresh_token", 0));
    }

    @Test
    @DisplayName("Account status changed event disables user and prevents login")
    void testAccountStatusChangedDisablesUser() throws Exception {
        // 1. Register user
        RegisterRequest registerReq = new RegisterRequest(
                "charlie@example.com",
                "charlie",
                "+212600000088",
                "Password123!",
                AccountKind.PERSONAL,
                "Charlie Brown"
        );
        mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(registerReq)))
                .andExpect(status().isCreated());

        // 2. Verify user can login
        LoginRequest loginReq = new LoginRequest("charlie", "Password123!");
        mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(loginReq)))
                .andExpect(status().isOk());

        // 3. Obtain user ID
        UUID userId = userRepository.findByUsername("charlie").orElseThrow().getId();

        // 4. Emit account status changed HTTP event with SERVICE authority
        String serviceToken = jwtService.issueServiceToken("customer-service", "SERVICE");
        String eventPayload = """
                {
                    "id": "%s",
                    "type": "customer.account.status-changed",
                    "data": {
                        "userId": "%s",
                        "previousStatus": "ACTIVE",
                        "newStatus": "BLOCKED",
                        "reason": "Suspected AML violation"
                    }
                }
                """.formatted(UUID.randomUUID(), userId);

        mockMvc.perform(post("/internal/auth/events")
                        .header("Authorization", "Bearer " + serviceToken)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(eventPayload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("PROCESSED"));

        // 5. Subsequent login must fail with 401 Unauthorized (Account is disabled)
        mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(loginReq)))
                .andExpect(status().isUnauthorized());
    }
}

