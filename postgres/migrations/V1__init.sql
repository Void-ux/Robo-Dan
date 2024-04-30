-- Revises: V0
-- Creation Date: 2024-02-20 14:20:25.168931 UTC
-- Reason: init

CREATE TABLE IF NOT EXISTS reminders
(
    id      BIGINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    expires TIMESTAMP,
    created TIMESTAMP DEFAULT NOW(),
    event   VARCHAR,
    extra   JSONB     DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS reminders_id_idx ON reminders (expires);

CREATE TABLE IF NOT EXISTS commands
(
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id   BIGINT,
    channel_id BIGINT,
    author_id  BIGINT,
    used       TIMESTAMP,
    prefix     TEXT,
    command    TEXT,
    slash      BOOLEAN,
    failed     BOOLEAN
);

-- File names/ids for Backblaze on downloaded files for DownloadControls panel
CREATE TABLE IF NOT EXISTS files
(
    message_id BIGINT PRIMARY KEY,
    file_name  TEXT NOT NULL,
    file_id    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_settings
(
    id BIGINT PRIMARY KEY, -- The discord user ID
    timezone TEXT -- The user's timezone
);

ALTER TABLE reminders ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC';
