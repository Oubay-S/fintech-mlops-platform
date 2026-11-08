package com.fintech.auth.domain;

import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "service_clients")
public class ServiceClient {

    @Id
    @Column(name = "client_id", nullable = false)
    private String clientId;

    @Column(name = "secret_hash", nullable = false)
    private String secretHash;

    @Column(nullable = false)
    private String role = "SERVICE";

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    public ServiceClient() {
    }

    public ServiceClient(String clientId, String secretHash, String role) {
        this.clientId = clientId;
        this.secretHash = secretHash;
        this.role = role != null ? role : "SERVICE";
        this.createdAt = Instant.now();
    }

    public String getClientId() {
        return clientId;
    }

    public void setClientId(String clientId) {
        this.clientId = clientId;
    }

    public String getSecretHash() {
        return secretHash;
    }

    public void setSecretHash(String secretHash) {
        this.secretHash = secretHash;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }
}

