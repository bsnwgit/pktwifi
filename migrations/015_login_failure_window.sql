-- When the last failed login happened, so failures older than the configured
-- window stop counting toward a lockout.
ALTER TABLE users ADD COLUMN last_failed_login TEXT;
