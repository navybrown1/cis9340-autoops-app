-- ============================================================================
-- CIS9340 Role-Based App Auth Bootstrap
-- Additive script: creates app-level users table for session auth.
-- Run this against cis9340_physical_database using a user with CREATE/INSERT rights.
-- ============================================================================

USE cis9340_physical_database;

CREATE TABLE IF NOT EXISTS users (
    user_id         INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(80)  NOT NULL UNIQUE,
    display_name    VARCHAR(120) NOT NULL,
    role            VARCHAR(32)  NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT chk_users_role
        CHECK (role IN ('admin', 'manager', 'frontdesk', 'mechanic', 'analyst'))
);

CREATE INDEX idx_users_role ON users (role);
CREATE INDEX idx_users_active ON users (is_active);

-- Seed users for first login pass.
-- Rotate passwords immediately after first successful sign-in.
-- Password format used for seed rows:
--   ChangeMe-<role>-2026!

INSERT INTO users (username, display_name, role, password_hash, is_active)
VALUES
    ('admin1', 'System Admin', 'admin', 'pbkdf2:sha256:1000000$LbuWV8xrPtwGBmhM$7e9352c004a3d01f40120733cb394b9f4bb9f13ec24deafe9c0c04999d4da482', 1),
    ('manager1', 'Branch Manager', 'manager', 'pbkdf2:sha256:1000000$rvY4uEOAHNGCrSMz$05dbc75215c02ea23c67e844615ccaebed60670b29dbec7012d90decd9cac876', 1),
    ('frontdesk1', 'Front Desk', 'frontdesk', 'pbkdf2:sha256:1000000$8tQYvWc0G7UWBSPH$46035fc772da8f1276b7359079b0897fb142cc6aa22e8820e477ca165c93cba0', 1),
    ('mechanic1', 'Repair Desk', 'mechanic', 'pbkdf2:sha256:1000000$ggDLrHvNgFxw1RxJ$02aadc6331743c05ad57aa63d8bba65f202cca3970e94402af08b089262e9c08', 1),
    ('analyst1', 'Reporting Analyst', 'analyst', 'pbkdf2:sha256:1000000$fm2oXtOmI24MZfpT$a9e4ce07972547addb216110838531ec6b26f008aa321aad50b7452a5a3ecc0f', 1)
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    role = VALUES(role),
    password_hash = VALUES(password_hash),
    is_active = VALUES(is_active);
