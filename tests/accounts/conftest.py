from pathlib import Path

import pytest
from apps.integrations.fakes import FakeHrisClient
from django_otp.plugins.otp_totp.models import TOTPDevice

from tests.factories import DEFAULT_PASSWORD, OrgUnitFactory, UserFactory


@pytest.fixture
def unit_adm(db):
    return OrgUnitFactory(code="ADM", name="Hành chính")


@pytest.fixture
def unit_itd(db):
    return OrgUnitFactory(code="ITD", name="CNTT")


@pytest.fixture
def pw_user(db):
    return UserFactory(username="bob")


@pytest.fixture
def user_with_totp(pw_user):
    TOTPDevice.objects.create(user=pw_user, name="default", confirmed=True)
    return pw_user


@pytest.fixture
def password():
    return DEFAULT_PASSWORD


@pytest.fixture
def fake_hris():
    return FakeHrisClient(Path(__file__).parent.parent / "fixtures" / "hris_small.json")
