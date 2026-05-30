-- 0027_admin_hub_revenue.sql
-- Admin Hub revenue / GCI tracking (migrated from Skyleigh's box).
-- Deal-sheet / CRM revenue fields. Especially important for referral files
-- where there is no MLS sale package, but Admin still needs to show what was
-- paid out (team vs agent split). Mirrors the columns already present in the
-- Postgres init schema (migrations_pg/0001_pg_init.sql) so the SQLite and PG
-- data paths stay in sync.

ALTER TABLE deals ADD COLUMN home_price REAL;
ALTER TABLE deals ADD COLUMN gci REAL;
ALTER TABLE deals ADD COLUMN team_revenue REAL;
ALTER TABLE deals ADD COLUMN agent_revenue REAL;
ALTER TABLE deals ADD COLUMN expected_close_date TEXT;
ALTER TABLE deals ADD COLUMN crm_transaction_status TEXT;
ALTER TABLE deals ADD COLUMN crm_transaction_type TEXT;
