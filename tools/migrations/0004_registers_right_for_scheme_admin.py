from django.db import migrations
from core.utils import insert_role_right_for_system


def add_rights(apps, schema_editor):
    insert_role_right_for_system(32, 131000)


class Migration(migrations.Migration):
    dependencies = [
        ('tools', '0003_auto_20211220_0920')
    ]

    operations = [
        migrations.RunPython(add_rights),
    ]
