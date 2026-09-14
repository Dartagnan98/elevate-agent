from elevate_cli.web_routes import kit_context


def test_retained_commission_subtracts_matching_tiers_and_preserves_overrides():
    values = {'listingCommission': 'Total listing commission: 6% on the first $100,000 and 3% on the balance, plus GST.',
              'buyerAgencyComp': 'Cooperating brokerage: 3% on the first $100,000 and 1.5% on the balance, plus GST.'}
    assert kit_context.retained_commission(values) == '3% on the first $100,000 and 1.5% on the balance, plus GST.'
    assert kit_context.retained_commission(dict(values, listingBrokerageRetained='Custom agreed fee')) == 'Custom agreed fee'
    assert kit_context.retained_commission(dict(values, listingBrokerageRetained='')) == ''
    for replacement in ['3% on the first $200,000 and 1.5% on the balance, plus GST.', 'Negotiated fee', '7% on the first $100,000 and 1.5% on the balance, plus GST.']:
        assert kit_context.retained_commission(dict(values, buyerAgencyComp=replacement)) == ''


def test_seller_mailing_address_is_separate_from_property_and_supports_deliberate_clear():
    values = {'sellerMailingAddress': '404-1395 Ellis Street, Kelowna, BC V1Y 1Z9'}
    assert kit_context.seller_mailing_parts(values) == {'sellerUnit':'404','sellerStreetNum':'1395','sellerStreet':'Ellis Street','sellerCity':'Kelowna','sellerState':'BC','sellerZip':'V1Y 1Z9'}
    assert not any(kit_context.seller_mailing_parts({'listingAddress':'123 Other Road, Town, BC V2B 1Z9'}).values())
    assert not any(kit_context.seller_mailing_parts({'sellerMailingAddress':'','onboardingSellers':[{'address':'123 Other Road, Town, BC V2B 1Z9'}]}).values())


def test_property_uses_lookup_parts_when_street_address_is_short():
    result = kit_context.property_parts("404-1395 Ellis Street", {"propertyCity": "Kelowna", "postalCode": "V1Y 1Z9"}, {"province": "BC"})
    assert result == {"p_unit": "404", "p_streetnum": "1395", "p_street": "Ellis Street", "p_city": "Kelowna", "p_state": "BC", "p_zip": "V1Y 1Z9"}


def test_two_agents_preferences_and_deliberate_override():
    preference = {"designatedAgency": "First Agent Corporation & Second Agent"}
    assert kit_context.agents({}, preference) == ("First Agent Corporation", "Second Agent")
    assert kit_context.agents({"designatedAgency": "Other Agent", "designatedAgency2": "Co Agent"}, preference) == ("Other Agent", "Co Agent")
    assert kit_context.agents({"designatedAgency": ""}, preference) == ("", "")


def test_offer_time_includes_am_pm():
    assert kit_context.clock_time("00:15") == "12:15 AM"
    assert kit_context.clock_time("12:30") == "12:30 PM"
    assert kit_context.clock_time("18:00") == "6:00 PM"
    assert kit_context.clock_time("") == ""


def test_listing_uses_saved_price_and_contract_start_separately_from_go_live():
    assert kit_context.listing_terms({"contractEffectiveDate":"2026-09-17","listingDate":"2026-09-18"}, {"listPrice":1024900}) == {"listPrice":1024900,"listDate":"2026-09-17"}
    assert kit_context.listing_terms({"listPrice":"","contractEffectiveDate":"","listingDate":"2026-09-18"}, {"listPrice":1024900}) == {"listPrice":"","listDate":""}
    assert kit_context.listing_terms({"listingDate":"2026-08-01"}, {})["listDate"] == "2026-08-01"
