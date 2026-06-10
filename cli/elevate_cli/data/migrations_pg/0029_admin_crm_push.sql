-- 0029_admin_crm_push.sql
-- Make CRM status-push a first-class ONBOARDING fact, not a loose config.yaml
-- flag. Lives next to crm_provider so it's captured at setup, flows into
-- ADMIN_ONBOARDING.md (the agent's per-account context), and drives the
-- lead_status CRM push.
--   crm_push_status: 'on' | 'off' (default off — opt-in to writing the live CRM)
--   crm_status_map:  JSON {our_status: "Their CRM Stage Name"} so our six
--                    pipeline statuses map to the realtor's actual CRM stages.
ALTER TABLE admin_setup_profile
    ADD COLUMN IF NOT EXISTS crm_push_status TEXT;
ALTER TABLE admin_setup_profile
    ADD COLUMN IF NOT EXISTS crm_status_map TEXT;
