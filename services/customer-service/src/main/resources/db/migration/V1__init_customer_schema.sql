-- Flyway migration for customer schema
-- Reference: APPLICATION_CONCEPTION_PLAN V2.3 Section 11 & 13.2

CREATE TABLE IF NOT EXISTS customers (
    user_id UUID PRIMARY KEY,
    display_name VARCHAR(100),
    email VARCHAR(255) NOT NULL UNIQUE,
    username VARCHAR(100) NOT NULL UNIQUE,
    phone VARCHAR(50),
    kyc_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    account_status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    account_kind VARCHAR(30) NOT NULL DEFAULT 'PERSONAL',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup indexes for receiver lookup and directory
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(LOWER(email));
CREATE INDEX IF NOT EXISTS idx_customers_username ON customers(LOWER(username));
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_customers_kind_status ON customers(account_kind, account_status);

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

