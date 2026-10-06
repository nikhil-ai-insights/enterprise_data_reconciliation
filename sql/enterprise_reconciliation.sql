-- Enterprise Data Architecture & Reconciliation
-- SQLite-compatible solution

-- REQUIRED: latest record per user, keeping only users whose latest status is Active.
WITH ranked_users AS (
    SELECT
        user_id,
        name,
        status,
        updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY datetime(updated_at) DESC, rowid DESC
        ) AS rn
    FROM users
)
SELECT
    user_id,
    name,
    status,
    updated_at
FROM ranked_users
WHERE rn = 1
  AND status = 'Active'
ORDER BY user_id;

-- Audit: latest status distribution.
WITH ranked_users AS (
    SELECT
        user_id,
        status,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY datetime(updated_at) DESC, rowid DESC
        ) AS rn
    FROM users
)
SELECT status, COUNT(*) AS latest_user_count
FROM ranked_users
WHERE rn = 1
GROUP BY status
ORDER BY latest_user_count DESC;

-- Audit: history depth per user.
SELECT user_id, COUNT(*) AS history_rows
FROM users
GROUP BY user_id
ORDER BY history_rows DESC, user_id;

-- Optional staging view for downstream transaction reconciliation.
DROP VIEW IF EXISTS latest_active_users;
CREATE VIEW latest_active_users AS
WITH ranked_users AS (
    SELECT
        user_id,
        name,
        status,
        updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY datetime(updated_at) DESC, rowid DESC
        ) AS rn
    FROM users
)
SELECT user_id, name, status, updated_at
FROM ranked_users
WHERE rn = 1 AND status = 'Active';
