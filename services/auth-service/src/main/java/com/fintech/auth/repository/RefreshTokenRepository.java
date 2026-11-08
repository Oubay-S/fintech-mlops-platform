package com.fintech.auth.repository;

import com.fintech.auth.domain.RefreshToken;
import com.fintech.auth.domain.User;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface RefreshTokenRepository extends JpaRepository<RefreshToken, UUID> {

    /**
     * Locks the token row with PESSIMISTIC_WRITE (SELECT ... FOR UPDATE).
     * This prevents concurrent refresh requests from both observing the token as valid
     * and each issuing a successor — ensuring strict one-time rotation guarantees.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    Optional<RefreshToken> findByTokenHash(String tokenHash);

    @Modifying
    @Query("UPDATE RefreshToken r SET r.revokedAt = :now WHERE r.user = :user AND r.revokedAt IS NULL")
    int revokeAllForUser(@Param("user") User user, @Param("now") Instant now);
}

