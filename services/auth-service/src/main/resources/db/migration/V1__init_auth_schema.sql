-- Flyway migration for auth schema
-- Reference: APPLICATION_CONCEPTION_PLAN V2.3 Section 13.2 & 13.3

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    username VARCHAR(100) NOT NULL UNIQUE,
    phone VARCHAR(50) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(50) NOT NULL,
    account_kind VARCHAR(50) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    device_info TEXT,
    ip_address VARCHAR(100),
    replaced_by UUID,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id UUID PRIMARY KEY,
    identifier VARCHAR(255) NOT NULL,
    ip_address VARCHAR(100) NOT NULL,
    was_successful BOOLEAN NOT NULL,
    failure_reason TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient lockout evaluation (5 failed attempts within 15 minutes)
CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier_attempted_at 
    ON login_attempts(identifier, attempted_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_attempted_at 
    ON login_attempts(ip_address, attempted_at);

CREATE TABLE IF NOT EXISTS service_clients (
    client_id VARCHAR(100) PRIMARY KEY,
    secret_hash TEXT NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'SERVICE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Outbox table for reliable domain event publishing (platform-starter)
CREATE TABLE IF NOT EXISTS outbox (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    type VARCHAR(100) NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ,
    attempts INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending 
    ON outbox(created_at) WHERE delivered_at IS NULL;

