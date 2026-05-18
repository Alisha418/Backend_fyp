# Generated migration for updating WorkerMonthlyStats

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workers', '0001_initial'),
    ]

    operations = [
        # Add points field
        migrations.AddField(
            model_name='workermonthlystats',
            name='points',
            field=models.IntegerField(default=0),
        ),
        # Update badge choices - this requires ALTER COLUMN in PostgreSQL
        # Note: For existing data, 'None' will need to be converted to 'Bronze' in a data migration if needed
        migrations.AlterField(
            model_name='workermonthlystats',
            name='badge',
            field=models.CharField(
                choices=[
                    ('Bronze', 'Bronze'),
                    ('Silver', 'Silver'),
                    ('Gold', 'Gold'),
                    ('Diamond', 'Diamond'),
                ],
                default='Bronze',
                max_length=20
            ),
        ),
    ]

