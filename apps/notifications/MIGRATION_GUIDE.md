# Notification Database Migration Guide

## Overview
This migration adds permanent database fields to the notifications table for better data persistence, cross-device sync, and improved filtering.

## New Database Fields

1. **`title`** (VARCHAR 255) - Permanent title storage
2. **`status`** (VARCHAR 20) - Notification status: 'pending', 'accepted', 'declined', 'expired'
3. **`expires_at`** (TIMESTAMP) - Timer expiry time
4. **`task_number`** (INTEGER) - Task number when accepted
5. **`accepted_at`** (TIMESTAMP) - Acceptance time
6. **`report_id`** (INTEGER) - Direct reference to report

## Migration Steps

### 1. Run Migration
```bash
cd "App backend"
python manage.py migrate notifications
```

### 2. Verify Migration
Check that new columns exist in database:
```sql
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'notifications';
```

### 3. Mark Expired Notifications (Optional - Run Periodically)
```bash
# Manual run
python manage.py mark_expired_notifications

# Or schedule via cron (every 5 minutes)
*/5 * * * * cd /path/to/project && python manage.py mark_expired_notifications
```

## Backend Changes

### Model Updates
- `Notification` model now includes new fields
- `NotificationStatus` enum added for status choices
- `mark_as_expired()` method added to model

### Serializer Updates
- `NotificationSerializer` now returns new fields
- Falls back to message JSON for backward compatibility
- Priority: Database fields > Message JSON

### View Updates
- Notification creation sets new fields
- Accept/decline endpoints update status and fields
- Direct `report_id` lookup instead of JSON parsing

## Frontend Changes

### Filter Logic
- **Assignments Tab**: Now excludes both declined AND expired notifications
- Uses database `status` field for filtering
- Falls back to `expires_at` check if status not available

### Data Priority
1. Database fields (title, status, expires_at, etc.)
2. SharedPreferences (for local persistence)
3. Message JSON (backward compatibility)

## Benefits

✅ **Permanent Storage**: Title, status, and expiry stored in database
✅ **Cross-Device Sync**: All devices see same notification state
✅ **Better Performance**: Direct field access instead of JSON parsing
✅ **Improved Filtering**: Expired notifications excluded from Assignments tab
✅ **Audit Trail**: Status changes tracked in database
✅ **Backward Compatible**: Still works with old message JSON format

## Testing

1. Create a new report → Check notification has all new fields
2. Accept a task → Verify status = 'accepted', task_number set
3. Decline a task → Verify status = 'declined', title updated
4. Wait for expiry → Run `mark_expired_notifications` → Verify status = 'expired'
5. Check Assignments tab → Should not show expired/declined notifications

## Rollback (If Needed)

```bash
python manage.py migrate notifications 0002
```

This will remove the new columns (data will be lost).

