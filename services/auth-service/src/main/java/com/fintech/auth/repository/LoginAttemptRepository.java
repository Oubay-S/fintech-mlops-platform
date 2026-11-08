package com.fintech.auth.repository;

import com.fintech.auth.domain.LoginAttempt;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.UUID;

@Repository
public interface LoginAttemptRepository extends JpaRepository<LoginAttempt, UUID> {

    @Query("SELECT COUNT(l) FROM LoginAttempt l " +
           "WHERE l.identifier = :identifier " +
           "AND l.ipAddress = :ipAddress " +
           "AND l.wasSuccessful = false " +
           "AND l.attemptedAt >= :since")
    long countFailedAttemptsSince(
            @Param("identifier") String identifier,
            @Param("ipAddress") String ipAddress,
            @Param("since") Instant since
    );
}

