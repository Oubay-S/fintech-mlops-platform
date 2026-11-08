package com.fintech.auth.service;

import com.fintech.auth.domain.AccountKind;
import com.fintech.auth.domain.Role;
import com.fintech.auth.domain.User;
import com.fintech.auth.dto.LoginRequest;
import com.fintech.auth.dto.LoginResult;
import com.fintech.auth.dto.RegisterRequest;
import com.fintech.auth.repository.LoginAttemptRepository;
import com.fintech.auth.repository.RefreshTokenRepository;
import com.fintech.auth.repository.ServiceClientRepository;
import com.fintech.auth.repository.UserRepository;
import com.fintech.auth.security.JwtService;
import com.fintech.auth.security.PasswordConfig;
import com.fintech.platform.error.BusinessException;
import com.fintech.platform.error.ErrorCode;
import com.fintech.platform.outbox.OutboxService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @Mock
    private UserRepository userRepository;
    @Mock
    private RefreshTokenRepository refreshTokenRepository;
    @Mock
    private LoginAttemptRepository loginAttemptRepository;
    @Mock
    private LoginAttemptService loginAttemptService;
    @Mock
    private ServiceClientRepository serviceClientRepository;
    @Mock
    private OutboxService outboxService;

    private PasswordEncoder passwordEncoder = new BCryptPasswordEncoder(12);
    private JwtService jwtService;
    private AuthService authService;

    @BeforeEach
    void setUp() {
        jwtService = new JwtService();
        jwtService.init();

        authService = new AuthService(
                userRepository,
                refreshTokenRepository,
                loginAttemptRepository,
                loginAttemptService,
                serviceClientRepository,
                passwordEncoder,
                jwtService,
                outboxService
        );
    }

    @Test
    @DisplayName("Registration succeeds and writes UserRegistered event to outbox")
    void testRegisterCustomerSuccess() {
        RegisterRequest req = new RegisterRequest(
                "john@example.com",
                "johndoe",
                "+1234567890",
                "Password123!",
                AccountKind.PERSONAL,
                "John Doe"
        );

        when(userRepository.existsByEmail("john@example.com")).thenReturn(false);
        when(userRepository.existsByUsername("johndoe")).thenReturn(false);
        when(userRepository.existsByPhone("+1234567890")).thenReturn(false);
        when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));

        User created = authService.registerCustomer(req);

        assertThat(created.getEmail()).isEqualTo("john@example.com");
        assertThat(created.getRole()).isEqualTo(Role.CUSTOMER);
        assertThat(passwordEncoder.matches("Password123!", created.getPasswordHash())).isTrue();

        verify(outboxService, times(1)).enqueue(argThat(env ->
                env.getType().equals("UserRegistered") &&
                "CUSTOMER".equals(env.getActor().getRole())
        ));
    }

    @Test
    @DisplayName("Lockout policy triggers when 5 failed attempts occur within 15 mins")
    void testLoginAccountLockout() {
        LoginRequest req = new LoginRequest("johndoe", "WrongPass");

        when(loginAttemptRepository.countFailedAttemptsSince(eq("johndoe"), eq("127.0.0.1"), any(Instant.class)))
                .thenReturn(5L);

        assertThatThrownBy(() -> authService.login(req, "127.0.0.1", "TestAgent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> assertThat(((BusinessException) ex).getErrorCode()).isEqualTo(ErrorCode.ACCOUNT_LOCKED));

        verify(userRepository, never()).findByUsername(any());
    }

    @Test
    @DisplayName("Successful login returns JWT and records success in login_attempts")
    void testLoginSuccess() {
        LoginRequest req = new LoginRequest("johndoe", "Secret123!");
        User user = new User(
                UUID.randomUUID(),
                "john@example.com",
                "johndoe",
                "+123456789",
                passwordEncoder.encode("Secret123!"),
                Role.CUSTOMER,
                AccountKind.PERSONAL
        );

        when(loginAttemptRepository.countFailedAttemptsSince(eq("johndoe"), eq("127.0.0.1"), any(Instant.class)))
                .thenReturn(0L);
        when(userRepository.findByEmail("johndoe")).thenReturn(Optional.empty());
        when(userRepository.findByUsername("johndoe")).thenReturn(Optional.of(user));

        LoginResult result = authService.login(req, "127.0.0.1", "Chrome");

        assertThat(result.response().accessToken()).isNotBlank();
        assertThat(result.rawRefreshToken()).isNotBlank();
        assertThat(result.response().roles()).contains("CUSTOMER");

        verify(loginAttemptService, times(1)).recordAttempt(eq("johndoe"), eq("127.0.0.1"), eq(true), isNull());
        verify(refreshTokenRepository, times(1)).save(any());
    }
}

