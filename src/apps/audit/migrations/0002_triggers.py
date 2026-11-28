from django.db import migrations

from apps.audit.triggers import drop_append_only_trigger, install_append_only_trigger


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [
        migrations.RunSQL(
            install_append_only_trigger("audit_auditevent"),
            reverse_sql=drop_append_only_trigger("audit_auditevent"),
        )
    ]
