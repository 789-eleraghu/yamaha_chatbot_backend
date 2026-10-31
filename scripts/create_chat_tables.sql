-- ============================================================================
-- CLICKHOUSE CHAT HISTORY TABLES
-- Run this script as ClickHouse admin user if api_client lacks CREATE privileges
-- ============================================================================

-- Table 1: chats - ReplacingMergeTree for update support
CREATE TABLE IF NOT EXISTS yamaha.chats (
    chat_id String,
    user_id String,
    name String DEFAULT 'New Chat',
    chat_context String DEFAULT '',
    context_updated_at Nullable(DateTime64(3)),
    summarized_up_to_message_id Nullable(Int64),
    is_archived UInt8 DEFAULT 0,
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),
    version UInt64 DEFAULT 1
) ENGINE = ReplacingMergeTree(version)
ORDER BY (chat_id)
PRIMARY KEY (chat_id);

-- Table 2: chat_history - append-only messages
CREATE TABLE IF NOT EXISTS yamaha.chat_history (
    message_id UUID DEFAULT generateUUIDv4(),
    chat_id String,
    role String,
    content String,
    created_at DateTime64(3) DEFAULT now64(3),
    model Nullable(String),
    token_count Nullable(Int32),
    metadata String DEFAULT '{}'
) ENGINE = MergeTree()
ORDER BY (chat_id, created_at, message_id)
PRIMARY KEY (chat_id, created_at);

-- Table 3: realtime_chat_events - append-only events
CREATE TABLE IF NOT EXISTS yamaha.realtime_chat_events (
    event_id String,
    chat_id String,
    message_id Nullable(String),
    event_type String,
    payload String DEFAULT '{}',
    created_at DateTime64(3) DEFAULT now64(3)
) ENGINE = MergeTree()
ORDER BY (chat_id, created_at)
PRIMARY KEY (chat_id);

-- Table 4: realtime_device_telemetry - live device status
CREATE TABLE IF NOT EXISTS yamaha.realtime_device_telemetry (
    device_id String,
    device_name String,
    category String,
    prefix String,
    voltage_avg Float64,
    current_avg Float64,
    power_factor Float64,
    real_power_kw Float64,
    apparent_power_kva Float64,
    reactive_power_kvar Float64,
    frequency_hz Float64,
    status String DEFAULT 'NORMAL',
    last_updated_ist DateTime64(3) DEFAULT now64(3),
    version UInt64 DEFAULT 1
) ENGINE = ReplacingMergeTree(version)
ORDER BY (device_id)
PRIMARY KEY (device_id);

-- Grant permissions to api_client
GRANT SELECT, INSERT ON yamaha.chats TO api_client;
GRANT SELECT, INSERT ON yamaha.chat_history TO api_client;
GRANT SELECT, INSERT ON yamaha.realtime_chat_events TO api_client;
GRANT SELECT, INSERT ON yamaha.realtime_device_telemetry TO api_client;
GRANT ALTER DELETE ON yamaha.chats TO api_client;
GRANT ALTER DELETE ON yamaha.chat_history TO api_client;
GRANT ALTER DELETE ON yamaha.realtime_chat_events TO api_client;
GRANT OPTIMIZE ON yamaha.chats TO api_client;
GRANT OPTIMIZE ON yamaha.realtime_device_telemetry TO api_client;
