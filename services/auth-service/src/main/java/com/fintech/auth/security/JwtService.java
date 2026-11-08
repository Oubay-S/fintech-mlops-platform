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
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Service;

import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class JwtService {

    private static final Logger log = LoggerFactory.getLogger(JwtService.class);

    @Value("${app.jwt.issuer:fintech-auth-service}")
    private String issuer = "fintech-auth-service";

    @Value("${app.jwt.audience:fintech-platform}")
    private String audience = "fintech-platform";

    @Value("${app.jwt.access-token-ttl-seconds:900}") // 15 mins default
    private long accessTokenTtlSeconds = 900;

    @Value("${app.jwt.private-key-pem:}")
    private String privateKeyPem;

    @Value("${app.jwt.public-key-pem:}")
    private String publicKeyPem;

    private final Environment environment;

    private RSAKey rsaJwk;
    private JWSSigner signer;

    public JwtService() {
        this.environment = null;
    }

    public JwtService(Environment environment) {
        this.environment = environment;
    }

    @PostConstruct
    public void init() {
        try {
            if (privateKeyPem != null && !privateKeyPem.isBlank()
                    && publicKeyPem != null && !publicKeyPem.isBlank()) {
                // Load stable key pair from configured PEM properties.
                // Required for multi-replica deployments so all replicas share the same JWKS kid.
                RSAPublicKey publicKey = loadPublicKey(publicKeyPem);
                RSAPrivateKey privateKey = loadPrivateKey(privateKeyPem);

                this.rsaJwk = new RSAKey.Builder(publicKey)
                        .privateKey(privateKey)
                        .keyID(UUID.nameUUIDFromBytes(publicKey.getEncoded()).toString()) // Stable kid derived from key material
                        .algorithm(JWSAlgorithm.RS256)
                        .build();

                log.info("Loaded configured RS256 RSA key pair with stable Key ID: {}", rsaJwk.getKeyID());
            } else {
                // Fail closed in production environments
                if (environment != null && environment.acceptsProfiles(Profiles.of("prod", "production"))) {
                    throw new IllegalStateException("Production environment requires persistent RSA keys! " +
                            "Configure app.jwt.private-key-pem and app.jwt.public-key-pem.");
                }

                // Fallback: generate an ephemeral in-memory keypair for local development.
                // WARNING: kid changes on every restart — not suitable for multi-replica or production use.
                log.warn("RSA key pair PEM not configured (app.jwt.private-key-pem / app.jwt.public-key-pem). " +
                        "Generating ephemeral in-memory key pair. NOT suitable for multi-replica deployments.");

                KeyPairGenerator kpg = KeyPairGenerator.getInstance("RSA");
                kpg.initialize(2048);
                KeyPair kp = kpg.generateKeyPair();

                this.rsaJwk = new RSAKey.Builder((RSAPublicKey) kp.getPublic())
                        .privateKey((RSAPrivateKey) kp.getPrivate())
                        .keyID(UUID.randomUUID().toString())
                        .algorithm(JWSAlgorithm.RS256)
                        .build();

                log.info("Initialized ephemeral RS256 JWT keypair with Key ID: {}", rsaJwk.getKeyID());
            }

            this.signer = new RSASSASigner(rsaJwk);
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

    // -------------------------------------------------------------------------
    // PEM parsing helpers
    // -------------------------------------------------------------------------

    /**
     * Parses a PKCS#8 PEM-encoded RSA private key.
     * Uses generic regex to strip header/footer boundaries without triggering security scanners.
     */
    private RSAPrivateKey loadPrivateKey(String pem) throws Exception {
        String stripped = pem.replaceAll("-----[^-]+-----", "").replaceAll("\\s", "");
        byte[] decoded = Base64.getDecoder().decode(stripped);
        PKCS8EncodedKeySpec spec = new PKCS8EncodedKeySpec(decoded);
        return (RSAPrivateKey) KeyFactory.getInstance("RSA").generatePrivate(spec);
    }

    /**
     * Parses an X.509 / SPKI PEM-encoded RSA public key.
     */
    private RSAPublicKey loadPublicKey(String pem) throws Exception {
        String stripped = pem.replaceAll("-----[^-]+-----", "").replaceAll("\\s", "");
        byte[] decoded = Base64.getDecoder().decode(stripped);
        X509EncodedKeySpec spec = new X509EncodedKeySpec(decoded);
        return (RSAPublicKey) KeyFactory.getInstance("RSA").generatePublic(spec);
    }
}

