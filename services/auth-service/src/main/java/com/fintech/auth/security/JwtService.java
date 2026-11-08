package com.fintech.auth.security;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.JWSSigner;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class JwtService {

    private static final Logger log = LoggerFactory.getLogger(JwtService.class);

    @Value("${app.jwt.issuer:fintech-auth-service}")
    private String issuer;

    @Value("${app.jwt.audience:fintech-platform}")
    private String audience;

    @Value("${app.jwt.access-token-ttl-seconds:900}") // 15 mins default
    private long accessTokenTtlSeconds;

    private RSAKey rsaJwk;
    private JWSSigner signer;

    @PostConstruct
    public void init() {
        try {
            // Generate in-memory 2048-bit RSA keypair on startup
            KeyPairGenerator kpg = KeyPairGenerator.getInstance("RSA");
            kpg.initialize(2048);
            KeyPair kp = kpg.generateKeyPair();

            RSAPublicKey publicKey = (RSAPublicKey) kp.getPublic();
            RSAPrivateKey privateKey = (RSAPrivateKey) kp.getPrivate();

            this.rsaJwk = new RSAKey.Builder(publicKey)
                    .privateKey(privateKey)
                    .keyID(UUID.randomUUID().toString())
                    .build();

            this.signer = new RSASSASigner(rsaJwk);
            log.info("Initialized RS256 JWT keypair with Key ID: {}", rsaJwk.getKeyID());
        } catch (Exception e) {
            throw new IllegalStateException("Failed to initialize RSA keypair for JWT signing", e);
        }
    }

    /**
     * Issues an RS256 JWT access token with claims required by V2.3 Section 10.2:
     * sub (user ID), roles, iss, aud, iat, exp, jti
     */
    public String issueAccessToken(UUID userId, List<String> roles) {
        Instant now = Instant.now();
        Instant expiry = now.plusSeconds(accessTokenTtlSeconds);

        JWTClaimsSet claimsSet = new JWTClaimsSet.Builder()
                .subject(userId.toString())
                .issuer(issuer)
                .audience(audience)
                .issueTime(Date.from(now))
                .expirationTime(Date.from(expiry))
                .jwtID(UUID.randomUUID().toString())
                .claim("roles", roles)
                .build();

        return signClaims(claimsSet);
    }

    /**
     * Issues an internal machine-to-machine SERVICE token with a 5-minute TTL.
     */
    public String issueServiceToken(String clientId, String role) {
        Instant now = Instant.now();
        Instant expiry = now.plusSeconds(300); // 5 minutes

        JWTClaimsSet claimsSet = new JWTClaimsSet.Builder()
                .subject(clientId)
                .issuer(issuer)
                .audience(audience)
                .issueTime(Date.from(now))
                .expirationTime(Date.from(expiry))
                .jwtID(UUID.randomUUID().toString())
                .claim("roles", List.of(role != null ? role : "SERVICE"))
                .build();

        return signClaims(claimsSet);
    }

    private String signClaims(JWTClaimsSet claimsSet) {
        try {
            SignedJWT signedJWT = new SignedJWT(
                    new JWSHeader.Builder(JWSAlgorithm.RS256)
                            .keyID(rsaJwk.getKeyID())
                            .build(),
                    claimsSet
            );
            signedJWT.sign(signer);
            return signedJWT.serialize();
        } catch (Exception e) {
            throw new IllegalStateException("Failed to sign JWT", e);
        }
    }

    /**
     * Exports public key JWKS for consumption by API Gateway and services.
     */
    public Map<String, Object> getJwks() {
        return new JWKSet(rsaJwk.toPublicJWK()).toJSONObject();
    }

    public RSAPublicKey getPublicKey() {
        try {
            return rsaJwk.toRSAPublicKey();
        } catch (Exception e) {
            throw new IllegalStateException("Failed to extract public key", e);
        }
    }

    public long getAccessTokenTtlSeconds() {
        return accessTokenTtlSeconds;
    }
}

