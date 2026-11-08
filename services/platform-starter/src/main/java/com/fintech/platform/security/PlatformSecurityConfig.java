package com.fintech.platform.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.security.web.SecurityFilterChain;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

/**
 * Common Spring Security configuration for Resource Servers.
 * - Stateless sessions (no HTTP session cookies)
 * - RS256 JWT token validation
 * - Extracts roles from token claims and maps them to Spring Security 'ROLE_' authorities
 * - Enables @PreAuthorize method security
 */
@Configuration
@EnableMethodSecurity
@org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean(SecurityFilterChain.class)
public class PlatformSecurityConfig {

    @Bean
    public SecurityFilterChain resourceServerSecurityFilterChain(HttpSecurity http) throws Exception {
        return http
                .csrf(AbstractHttpConfigurer::disable)
                .cors(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        // Public actuator endpoints (liveness, readiness, prometheus)
                        .requestMatchers("/actuator/health/**", "/actuator/prometheus").permitAll()
                        // Public OpenAPI docs
                        .requestMatchers("/v3/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                        // All other endpoints require authenticated JWT
                        .anyRequest().authenticated()
                )
                .oauth2ResourceServer(oauth2 -> oauth2
                        .jwt(jwt -> jwt.jwtAuthenticationConverter(jwtAuthenticationConverter()))
                )
                .build();
    }

    @Bean
    public Converter<Jwt, ? extends AbstractAuthenticationToken> jwtAuthenticationConverter() {
        return jwt -> {
            Collection<GrantedAuthority> authorities = extractAuthorities(jwt);
            return new JwtAuthenticationToken(jwt, authorities, jwt.getSubject());
        };
    }

    private Collection<GrantedAuthority> extractAuthorities(Jwt jwt) {
        List<GrantedAuthority> authorities = new ArrayList<>();

        // 1. Check for 'roles' claim (e.g. ["CUSTOMER", "ANALYST", "ADMIN", "SERVICE"])
        Object rolesClaim = jwt.getClaims().get("roles");
        if (rolesClaim instanceof Collection<?> roles) {
            for (Object role : roles) {
                if (role != null) {
                    String roleStr = role.toString();
                    if (!roleStr.startsWith("ROLE_")) {
                        authorities.add(new SimpleGrantedAuthority("ROLE_" + roleStr));
                    } else {
                        authorities.add(new SimpleGrantedAuthority(roleStr));
                    }
                }
            }
        }

        // 2. Fallback check for single 'role' claim
        Object singleRole = jwt.getClaims().get("role");
        if (singleRole != null) {
            String roleStr = singleRole.toString();
            if (!roleStr.startsWith("ROLE_")) {
                authorities.add(new SimpleGrantedAuthority("ROLE_" + roleStr));
            } else {
                authorities.add(new SimpleGrantedAuthority(roleStr));
            }
        }

        return authorities;
    }
}

