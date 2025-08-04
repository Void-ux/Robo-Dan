-- Revises: V1
-- Creation Date: 2025-07-31 13:52:10.940679 UTC
-- Reason: todos

CREATE TABLE IF NOT EXISTS todo (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT,
    message_id BIGINT,
    guild_id BIGINT,
    due_date TIMESTAMP,
    content TEXT,
    completed_at TIMESTAMP,
    cached_content TEXT,
    timezone TEXT NOT NULL DEFAULT 'UTC'
    reminder_triggered BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS todo_user_id_idx ON todo(user_id);
CREATE INDEX IF NOT EXISTS todo_message_id_idx ON todo(message_id);
CREATE INDEX IF NOT EXISTS todo_completed_at_idx ON todo(completed_at);
CREATE INDEX IF NOT EXISTS todo_due_date_idx ON todo(due_date);
