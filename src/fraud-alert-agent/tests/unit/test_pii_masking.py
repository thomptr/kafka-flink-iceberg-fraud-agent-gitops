import pytest

from app.tools.pii_masking import mask_pii


def test_card_number_masked():
    assert mask_pii("card 4111 1111 1111 1234") == "card ****-****-****-1234"


def test_card_number_no_spaces_masked():
    result = mask_pii("4111111111111234")
    assert "1234" in result
    assert "4111" not in result


def test_ssn_masked():
    assert mask_pii("ssn 123-45-6789") == "ssn ***-**-****"


def test_email_masked():
    assert mask_pii("contact analyst@example.com today") == "contact [email redacted] today"


def test_non_pii_passthrough():
    assert mask_pii("merchant: Starbucks, amount: 4.50") == "merchant: Starbucks, amount: 4.50"


def test_nested_dict():
    data = {"card": "4111 1111 1111 1234", "name": "Alice"}
    result = mask_pii(data)
    assert "4111" not in result["card"]
    assert result["name"] == "Alice"


def test_list_of_strings():
    data = ["123-45-6789", "nothing here", "test@test.com"]
    result = mask_pii(data)
    assert result[0] == "***-**-****"
    assert result[1] == "nothing here"
    assert result[2] == "[email redacted]"


def test_non_string_passthrough():
    assert mask_pii(42) == 42
    assert mask_pii(3.14) == 3.14
    assert mask_pii(None) is None
