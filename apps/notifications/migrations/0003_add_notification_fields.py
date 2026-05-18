# Generated migration for adding notification fields
# Run: python manage.py migrate notifications

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_delete_offlinesyncqueue_alter_notification_options'),
    ]

    operations = [
        # Add new fields to notifications table
        migrations.RunSQL(
            # SQL to add new columns (PostgreSQL syntax)
            sql="""
                ALTER TABLE notifications 
                ADD COLUMN IF NOT EXISTS title VARCHAR(255) NULL,
                ADD COLUMN IF NOT EXISTS status VARCHAR(20) NULL,
                ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL,
                ADD COLUMN IF NOT EXISTS task_number INTEGER NULL,
                ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP NULL,
                ADD COLUMN IF NOT EXISTS report_id INTEGER NULL;
                
                -- Create indexes for better query performance
                CREATE INDEX IF NOT EXISTS idx_notifications_title ON notifications(title);
                CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
                CREATE INDEX IF NOT EXISTS idx_notifications_expires_at ON notifications(expires_at);
                CREATE INDEX IF NOT EXISTS idx_notifications_report_id ON notifications(report_id);
                
                -- Set default status for existing notifications
                UPDATE notifications 
                SET status = 'pending' 
                WHERE status IS NULL;
            """,
            reverse_sql="""
                -- Drop indexes
                DROP INDEX IF EXISTS idx_notifications_title;
                DROP INDEX IF EXISTS idx_notifications_status;
                DROP INDEX IF EXISTS idx_notifications_expires_at;
                DROP INDEX IF EXISTS idx_notifications_report_id;
                
                -- Drop columns
                ALTER TABLE notifications 
                DROP COLUMN IF EXISTS title,
                DROP COLUMN IF EXISTS status,
                DROP COLUMN IF EXISTS expires_at,
                DROP COLUMN IF EXISTS task_number,
                DROP COLUMN IF EXISTS accepted_at,
                DROP COLUMN IF EXISTS report_id;
            """
        ),
        # Migrate existing data from message JSON to new fields
        migrations.RunSQL(
            sql="""
                -- Extract title from message JSON
                UPDATE notifications 
                SET title = COALESCE(
                    (message::json->>'title'),
                    (message::json->>'message'),
                    'Notification'
                )
                WHERE title IS NULL AND message IS NOT NULL 
                AND message::text LIKE '{%';
                
                -- Extract report_id from message JSON
                UPDATE notifications 
                SET report_id = (message::json->>'report_id')::INTEGER
                WHERE report_id IS NULL AND message IS NOT NULL 
                AND message::text LIKE '{%'
                AND (message::json->>'report_id') IS NOT NULL;
                
                -- Extract expires_at from message JSON
                UPDATE notifications 
                SET expires_at = (message::json->>'expires_at')::TIMESTAMP
                WHERE expires_at IS NULL AND message IS NOT NULL 
                AND message::text LIKE '{%'
                AND (message::json->>'expires_at') IS NOT NULL;
            """,
            reverse_sql="""
                -- No reverse needed - data migration only
            """
        ),
    ]

