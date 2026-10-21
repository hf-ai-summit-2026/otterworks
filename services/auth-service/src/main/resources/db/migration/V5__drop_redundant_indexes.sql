-- users.email and refresh_tokens.token_id are UNIQUE, so Postgres already indexes them;
-- these duplicates only add write cost to every registration, login and refresh.
DROP INDEX IF EXISTS idx_users_email;
DROP INDEX IF EXISTS idx_refresh_tokens_token_id;
