-- 0015_xposure_pcs_identity_kind.sql
-- Allow the MLS Buyer Searches connector to store the native Xposure/PCS
-- buyer id as an identity. This lets a PCS row that resolves into an existing
-- CRM contact still be mapped back for pcs_buyers upsert.

ALTER TABLE identities
    DROP CONSTRAINT IF EXISTS identities_kind_check;

ALTER TABLE identities
    ADD CONSTRAINT identities_kind_check CHECK (kind IN (
        'email','phone',
        'instagram_id','instagram_handle',
        'facebook_id','telegram_id',
        'lofty_id','fub_id','sierra_id','brivity_id','boldtrail_id',
        'xposure_pcs_id',
        'apple_handle','apple_addressbook_id','apple_chat_id',
        'wa_id'
    ));
