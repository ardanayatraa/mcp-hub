"""Field names that always stay hidden from AI, whatever the app's own policy says."""

import pytest
from app.security.authorization import is_sensitive_path


@pytest.mark.parametrize("name", ["otp", "otp_code", "smsOtp", "pin", "pin_code", "cvv", "card_cvc", "verification_code",
                                  "authCode", "msisdn", "customer_msisdn", "card_number", "iban", "bank_account_number",
                                  "passport_no", "npwp", "ktp_number", "owner_email", "contactPhone"])
def test_credentials_and_identifiers_are_always_hidden(name):
    assert is_sensitive_path(name)


@pytest.mark.parametrize("name", ["is_pinned", "spinner", "options", "topic", "status", "price", "provider", "created_at",
                                  "emailed_at_count", "account_type"])
def test_ordinary_names_are_not_caught(name):
    assert not is_sensitive_path(name)
