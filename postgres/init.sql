CREATE TABLE IF NOT EXISTS reminders
(
    id      BIGINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    expires TIMESTAMP,
    created TIMESTAMP DEFAULT NOW(),
    event   VARCHAR,
    extra   JSONB     DEFAULT '{}'::JSONB
);

CREATE INDEX ON reminders (expires);
--
-- Misc
--

-- Every command ever invoked is added here, currently only supports on_command_completion (not app commands)
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
)
