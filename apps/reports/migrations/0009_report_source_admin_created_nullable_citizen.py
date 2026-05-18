# Generated manually — admin-created reports no longer use placeholder citizen_id=1

import django.db.models.deletion
from django.db import migrations, models


def clear_placeholder_citizen(apps, schema_editor):
    """Legacy admin tasks used Account pk=1 as placeholder; detach from citizen."""
    Report = apps.get_model('reports', 'Report')
    Report.objects.filter(citizen_id_id=1).update(
        citizen_id=None,
        report_source='admin',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0008_report_location_address'),
        ('admins', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='report_source',
            field=models.CharField(
                choices=[('citizen', 'Citizen'), ('admin', 'Admin')],
                db_index=True,
                default='citizen',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='report',
            name='created_by_admin',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='admin_created_reports',
                to='admins.admin',
            ),
        ),
        migrations.AlterField(
            model_name='report',
            name='citizen_id',
            field=models.ForeignKey(
                blank=True,
                db_column='citizen_id',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='submitted_reports',
                to='accounts.account',
            ),
        ),
        migrations.RunPython(clear_placeholder_citizen, noop_reverse),
    ]
