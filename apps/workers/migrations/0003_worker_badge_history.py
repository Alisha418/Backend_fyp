from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0002_update_worker_monthly_stats"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerBadgeHistory",
            fields=[
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "badge",
                    models.CharField(
                        choices=[
                            ("Bronze", "Bronze"),
                            ("Silver", "Silver"),
                            ("Gold", "Gold"),
                            ("Diamond", "Diamond"),
                        ],
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("is_current", models.BooleanField(db_index=True, default=True)),
                (
                    "worker_id",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="badge_history",
                        to="workers.worker",
                    ),
                ),
            ],
            options={
                "db_table": "Badge_History",
                "ordering": ["-started_at"],
            },
        ),
        migrations.AddIndex(
            model_name="workerbadgehistory",
            index=models.Index(fields=["worker_id", "-started_at"], name="Badge_Histo_worker__629be2_idx"),
        ),
        migrations.AddIndex(
            model_name="workerbadgehistory",
            index=models.Index(fields=["worker_id", "is_current"], name="Badge_Histo_worker__fc0594_idx"),
        ),
    ]
