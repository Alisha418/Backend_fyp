# Generated manually for uniq_report_citizen_client_temp_id

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0006_report_citizen_temp_id_is_synced'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='report',
            constraint=models.UniqueConstraint(
                condition=models.Q(citizen_temp_id__isnull=False)
                & ~models.Q(citizen_temp_id=''),
                fields=('citizen_id', 'citizen_temp_id'),
                name='uniq_report_citizen_client_temp_id',
            ),
        ),
    ]
