from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0005_report_resolved_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='citizen_temp_id',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='report',
            name='is_synced',
            field=models.BooleanField(blank=True, null=True),
        ),
    ]

