import factory
from django.contrib.auth import get_user_model

from apps.accounts.models import OrgUnit

DEFAULT_PASSWORD = "dung-mat-khau-123"


class OrgUnitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrgUnit

    code = factory.Sequence(lambda n: f"DV{n:03d}")
    name = factory.Sequence(lambda n: f"Đơn vị {n}")
    kind = OrgUnit.Kind.PHONG


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.test")

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or DEFAULT_PASSWORD)
        if create:
            self.save(update_fields=["password"])
