package com.fintech.auth.controller;

import com.fintech.auth.security.JwtService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/.well-known")
public class JwksController {

    private final JwtService jwtService;

    public JwksController(JwtService jwtService) {
        this.jwtService = jwtService;
    }

    @GetMapping(value = "/jwks.json", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> getJwks() {
        return jwtService.getJwks();
    }
}

