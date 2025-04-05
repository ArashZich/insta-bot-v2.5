-- تنظیمات اولیه برای دیتابیس Instagram Bot

-- ایجاد جدول برای ثبت آخرین عملیات موفق پشتیبان‌گیری
CREATE TABLE IF NOT EXISTS backup_history (
    id SERIAL PRIMARY KEY,
    backup_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    backup_path TEXT,
    backup_size BIGINT,
    backup_type TEXT,
    status TEXT
);

-- تنظیم ایندکس‌های ضروری
CREATE INDEX IF NOT EXISTS idx_bot_activities_type ON bot_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_bot_activities_date ON bot_activities(created_at);
CREATE INDEX IF NOT EXISTS idx_user_followings_is_following ON user_followings(is_following);
CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date);

-- تنظیم برنامه زمانی VACUUM خودکار
ALTER DATABASE "${POSTGRES_DB}" SET maintenance_work_mem = '128MB';