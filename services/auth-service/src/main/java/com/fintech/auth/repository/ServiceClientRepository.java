package com.fintech.auth.repository;

import com.fintech.auth.domain.ServiceClient;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface ServiceClientRepository extends JpaRepository<ServiceClient, String> {
}

