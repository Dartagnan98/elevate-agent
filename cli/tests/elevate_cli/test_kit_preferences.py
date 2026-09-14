import pytest
from elevate_cli.web_routes.kit_preferences import read_preferences, write_preferences


def test_roundtrip_is_account_scoped_and_preserves_contract_wording(tmp_path):
    first, second = tmp_path/'a'/'document-kit.json', tmp_path/'b'/'document-kit.json'
    assert read_preferences(first) == {}
    saved = write_preferences({'cpsDepositTerms':'Within 24 hours of subject removal', 'cpsDepositHolder':'Example Brokerage, in trust', 'designatedAgency':'Agent A'}, first)
    assert read_preferences(first) == saved
    assert read_preferences(second) == {}
    assert saved['cpsDepositHolder'] == 'Example Brokerage, in trust'
    assert write_preferences({}, first)['cpsDepositTerms'] == ''


def test_preferences_cannot_store_transaction_prices_or_dates(tmp_path):
    with pytest.raises(ValueError): write_preferences({'cpsPurchasePrice':'500000'},tmp_path/'prefs')
    with pytest.raises(ValueError): write_preferences({'completionDate':'2026-10-01'},tmp_path/'prefs')
    with pytest.raises(ValueError): write_preferences({'cpsDepositTerms': ['invalid']},tmp_path/'prefs')
