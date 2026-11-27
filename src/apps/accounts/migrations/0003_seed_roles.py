from django.db import migrations

from apps.accounts.roles import ROLE_NAMES


def seed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for code, name in ROLE_NAMES.items():
        Role.objects.update_or_create(code=code, defaults={"name": name})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_org_roles_user_fields")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
