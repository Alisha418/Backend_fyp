from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0009_report_source_admin_created_nullable_citizen'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='ai_categories',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
