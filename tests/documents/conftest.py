import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests.factories import OrgUnitFactory, UserFactory
from tests.testapp.models import Dummy
from tests.documents.helpers import pdf_with_text


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def unit(db):
    return OrgUnitFactory()


@pytest.fixture
def owner(unit):
    return UserFactory(username="owner", org_unit=unit)


@pytest.fixture
def outsider(db):
    return UserFactory(username="outsider", org_unit=OrgUnitFactory())


@pytest.fixture
def req(owner, unit):
    return Dummy.objects.create(owner=owner, unit=unit)


@pytest.fixture
def pdf_doc(owner, req):
    from apps.documents.models import CONTRACT
    from apps.documents.storage import store_upload

    return store_upload(
        SimpleUploadedFile("hop-dong.pdf", pdf_with_text("Hop dong thue kho Chuong Duong")),
        attach_to=req,
        doc_type=CONTRACT,
        user=owner,
    )
