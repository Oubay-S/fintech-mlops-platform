package com.fintech.auth.controller;

import com.fintech.auth.dto.ServiceTokenRequest;
import com.fintech.auth.dto.ServiceTokenResponse;
import com.fintech.auth.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/auth")
public class InternalAuthController {

    private final AuthService authService;

    public InternalAuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/service-token")
    public ResponseEntity<ServiceTokenResponse> getServiceToken(@Valid @RequestBody ServiceTokenRequest request) {
        ServiceTokenResponse response = authService.issueServiceToken(request);
        return ResponseEntity.ok(response);
    }
}

