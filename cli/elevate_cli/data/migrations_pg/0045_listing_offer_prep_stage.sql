-- 0045_listing_offer_prep_stage.sql
--
-- The listing board gained an Offer Prep column at stage 6 so its tail matches
-- the buyer board (Offer Prep -> Accepted -> Condition Removal -> Subjects Off).
-- Everything that used to sit at 6/7/8 is now 7/8/9:
--
--   6 Accepted Offer   -> 7 Accepted
--   7 Condition Removal-> 8 Condition Removal
--   8 Closed           -> 9 Subjects Off
--
-- Descending order matters: shifting 6 first would collide with the rows still
-- at 7. Buyer deals are untouched (their stages did not move). Stage 9 is the
-- current_stage CHECK ceiling, so nothing can be pushed out of range - anything
-- already at 9 (an out-of-flow import) stays put.

UPDATE deals SET current_stage = 9 WHERE side = 'listing' AND current_stage = 8;
UPDATE deals SET current_stage = 8 WHERE side = 'listing' AND current_stage = 7;
UPDATE deals SET current_stage = 7 WHERE side = 'listing' AND current_stage = 6;

-- Already-seeded conditional docs that hung off the old Accepted Offer (6)
-- move with it. A re-import of the province pack writes the same values
-- (province_guides._DEFAULT_CONDITIONAL_DOCS); this is for installs that
-- imported before the shift.
UPDATE conditional_docs SET stage = 7
 WHERE province = 'BC' AND stage = 6 AND doc_code IN ('strata_docs', 'offer_matrix');
