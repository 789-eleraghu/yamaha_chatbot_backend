# Chatbot Chat History Schema (PostgreSQL)

**Database:** Yamaha DB
**Tables:** `chats`, `chat_history`

## 1. Design overview

Two tables instead of one:

| Table | Grain | Holds |
|---|---|---|
| `chats` | one row per chat | id, owner, name, running summary (`chat_context`), timestamps |
| `chat_history` | one row per message | role, content, timestamp, token count, metadata |

Why split: `name` and `chat_context` belong to the *chat*, not to each message. If they lived on every message row, updating the summary would mean rewriting every row of that chat, and copies could drift apart. With two tables, a summary update is a single-row `UPDATE`.

## 2. DDL

```sql
-- gen_random_uuid() is built in on PostgreSQL 13+.
-- On older versions: CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE chats (
    chat_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     TEXT NOT NULL,
    name                        TEXT,
    chat_context                TEXT NOT NULL DEFAULT '',
    context_updated_at          TIMESTAMPTZ,
    summarized_up_to_message_id BIGINT,
    is_archived                 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_history (
    message_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id      UUID NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    model        TEXT,
    token_count  INTEGER,
    metadata     JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_chat_history_chat_time
    ON chat_history (chat_id, created_at, message_id);

CREATE INDEX idx_chats_user_updated
    ON chats (user_id, updated_at DESC);
```

## 3. Column reference

### `chats`

| Column | Type | Notes |
|---|---|---|
| `chat_id` | UUID PK | Safe to expose in URLs/APIs (not guessable) |
| `user_id` | TEXT | Owner of the chat. Match this to your users table / auth ID type (change to `INTEGER` or `UUID` and add an FK if you have one) |
| `name` | TEXT | Chat title. Can be auto-generated from the first message |
| `chat_context` | TEXT | Running summary. Updated in place |
| `context_updated_at` | TIMESTAMPTZ | When the summary was last refreshed |
| `summarized_up_to_message_id` | BIGINT | Last message already folded into the summary. Lets you summarize only newer messages next time |
| `is_archived` | BOOLEAN | Hide from the sidebar without deleting |
| `created_at` / `updated_at` | TIMESTAMPTZ | `updated_at` drives "recent chats" ordering. Bump it on every new message |

### `chat_history`

| Column | Type | Notes |
|---|---|---|
| `message_id` | BIGINT identity PK | Monotonic, so it also gives a reliable ordering tie-breaker |
| `chat_id` | UUID FK | `ON DELETE CASCADE`: deleting a chat removes its messages |
| `role` | TEXT | `system`, `user`, `assistant`, `tool` (constrained by CHECK) |
| `content` | TEXT | The message text |
| `created_at` | TIMESTAMPTZ | Message timestamp |
| `model` | TEXT | Which LLM produced an assistant message |
| `token_count` | INTEGER | For context-window budgeting and cost tracking |
| `metadata` | JSONB | Flexible: tool calls, finish reason, latency, feedback, errors |

## 4. Common queries

**Create a chat**
```sql
INSERT INTO chats (user_id, name)
VALUES ($1, $2)
RETURNING chat_id;
```

**Save a message and bump the chat's `updated_at`** (do both in one transaction)
```sql
BEGIN;

INSERT INTO chat_history (chat_id, role, content, model, token_count, metadata)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING message_id;

UPDATE chats SET updated_at = now() WHERE chat_id = $1;

COMMIT;
```

**Load a chat's messages in order**
```sql
SELECT message_id, role, content, created_at
FROM chat_history
WHERE chat_id = $1
ORDER BY created_at, message_id;
```

**Load the last N messages for the LLM prompt** (returned oldest-first)
```sql
SELECT * FROM (
    SELECT message_id, role, content
    FROM chat_history
    WHERE chat_id = $1
    ORDER BY created_at DESC, message_id DESC
    LIMIT 20
) recent
ORDER BY message_id;
```

**List a user's chats for the sidebar**
```sql
SELECT chat_id, name, updated_at
FROM chats
WHERE user_id = $1 AND NOT is_archived
ORDER BY updated_at DESC
LIMIT 50;
```

**Update the summary**
```sql
UPDATE chats
SET chat_context = $1,
    context_updated_at = now(),
    summarized_up_to_message_id = $2,
    updated_at = now()
WHERE chat_id = $3;
```

**Fetch only messages not yet summarized**
```sql
SELECT message_id, role, content
FROM chat_history
WHERE chat_id = $1
  AND message_id > COALESCE(
        (SELECT summarized_up_to_message_id FROM chats WHERE chat_id = $1), 0)
ORDER BY message_id;
```

## 5. Summary-refresh flow

1. After each assistant reply (or every N messages), fetch the un-summarized messages (query above).
2. Send the existing `chat_context` plus those new messages to the LLM with an instruction like: *"Update this summary to include the new messages. Keep it under X words."*
3. Write the result back with the `UPDATE` above, setting `summarized_up_to_message_id` to the newest message included.
4. Rewrite or condense the summary rather than only appending, otherwise it grows without bound.

## 6. Building the prompt for the model

Typical context assembly:

1. System prompt
2. `chat_context` (the summary) as extra context
3. Most recent messages, loaded newest-first until you hit your token budget (use `token_count`)
4. The new user message

## 7. Optional extensions

| Addition | When you need it |
|---|---|
| `parent_message_id BIGINT REFERENCES chat_history(message_id)` | Branching or regenerated responses |
| `deleted_at TIMESTAMPTZ` | Soft deletes |
| `status TEXT` (`complete`, `error`, `partial`) | Streaming responses where you want to mark incomplete ones |
| Index on `metadata` (`USING GIN`) | Only if you start filtering by JSONB fields |
| Partitioning `chat_history` by `created_at` | Only at very large volume |
| Full-text index on `content` (`tsvector` + GIN) | Search across chat history |

## 8. Practical notes

- **Use `TIMESTAMPTZ`, not `TIMESTAMP`**, to avoid timezone bugs. Store UTC and convert in the UI.
- **Sort by `message_id` as a tie-breaker**; two messages can share a timestamp.
- **Wrap message insert + `updated_at` bump in one transaction** so the sidebar order stays correct.
- **`TEXT` has no practical length limit** in Postgres, so no need for `VARCHAR(n)` on `content` or `chat_context`.
- **Keep the table names distinct from existing ones in the Yamaha DB.** Run `\dt` first to confirm `chats` and `chat_history` don't already exist.
- **Authorization:** always filter by `user_id` when a user requests a chat (`WHERE chat_id = $1 AND user_id = $2`), so one user can't read another's chat by guessing an ID.
- **Cleanup:** deleting from `chats` cascades to `chat_history`. Archive instead of delete if you want to keep history.
