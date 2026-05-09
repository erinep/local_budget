import pytest
from app import net_amount


def make_row(desc, amount):
    return {"Description 1": desc, "CAD$": amount}


# --- Non-tracked keywords → always 0 ---

def test_payment_is_zeroed():
    assert net_amount(make_row("CREDIT CARD PAYMENT", -500.00)) == 0


def test_transfer_is_zeroed():
    assert net_amount(make_row("E-TRANSFER TO JOHN", -200.00)) == 0


def test_autopay_is_zeroed():
    assert net_amount(make_row("AUTOPAY HYDRO", -80.00)) == 0


def test_thank_you_is_zeroed():
    assert net_amount(make_row("THANK YOU", 50.00)) == 0


def test_keyword_check_is_case_insensitive():
    assert net_amount(make_row("credit card payment", -100.00)) == 0


# --- Real spend: negative CAD$ (money out) → positive net ---

def test_negative_amount_becomes_positive():
    assert net_amount(make_row("TIM HORTONS", -4.50)) == 4.50


# --- Credits / refunds: positive CAD$ → negative net ---

def test_positive_amount_becomes_negative():
    assert net_amount(make_row("REFUND FROM AMAZON", 25.00)) == -25.00


# --- Edge cases ---

def test_zero_amount():
    assert net_amount(make_row("SOME MERCHANT", 0)) == 0
