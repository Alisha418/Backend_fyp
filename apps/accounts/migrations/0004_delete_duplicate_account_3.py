# Data migration: remove duplicate Account row pk=3 (admin email in accounts table).
# Detach reports first so CASCADE does not delete them.

from django.db import migrations


def forwards(apps, schema_editor):
    Report = apps.get_model('reports', 'Report')
    Account = apps.get_model('accounts', 'Account')
    Feedback = apps.get_model('feedback', 'Feedback')

    if not Account.objects.filter(account_id=3).exists():
        return

    # Feedback requires a citizen FK; remove rows for citizen 3 before deleting Account.
    Feedback.objects.filter(citizen_id_id=3).delete()

    Report.objects.filter(citizen_id_id=3).update(citizen_id=None, report_source='admin')

    Account.objects.filter(account_id=3).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_alter_loginhistory_status'),
        ('reports', '0009_report_source_admin_created_nullable_citizen'),
        ('feedback', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, noop_reverse),
    ]
