-- Verification queries for notification migration
-- Run these to verify columns were added successfully

-- 1. Check if all new columns exist
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'notifications' 
AND column_name IN ('title', 'status', 'expires_at', 'task_number', 'accepted_at', 'report_id')
ORDER BY column_name;

-- 2. Check if indexes were created
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'notifications' 
AND indexname LIKE 'idx_notifications_%';

-- 3. Check current notification count and sample data
SELECT 
    notification_id,
    recipient_type,
    title,
    status,
    expires_at,
    report_id
FROM notifications 
LIMIT 5;




