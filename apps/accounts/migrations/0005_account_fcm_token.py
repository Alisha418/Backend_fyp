from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_delete_duplicate_account_3'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='fcm_token',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='fcm_token_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
