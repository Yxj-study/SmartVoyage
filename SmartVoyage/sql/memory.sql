CREATE TABLE IF NOT EXISTS travel_user_preferences (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    preference_key VARCHAR(64) NOT NULL,
    value_json JSON NOT NULL,
    confidence DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
    source_session_id VARCHAR(128) NOT NULL,
    source_text TEXT NOT NULL,
    status ENUM('active', 'deleted') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_preference (user_id, preference_key),
    KEY idx_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS travel_preference_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    preference_key VARCHAR(64) NOT NULL,
    operation ENUM('upsert', 'delete') NOT NULL,
    old_value_json JSON NULL,
    new_value_json JSON NULL,
    source_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_event_user_created (user_id, created_at),
    KEY idx_event_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
