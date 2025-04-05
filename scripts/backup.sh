#!/bin/bash

# اسکریپت پشتیبان‌گیری از دیتابیس Instagram Bot

# تنظیم متغیرهای زمانی
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/backup"
MAX_BACKUPS=7

# ایجاد دایرکتوری پشتیبان‌گیری
mkdir -p $BACKUP_DIR

# پشتیبان‌گیری از دیتابیس
echo "Taking database backup at $TIMESTAMP..."
pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE -F c -f "$BACKUP_DIR/instagram_bot_$TIMESTAMP.backup"

if [ $? -eq 0 ]; then
  echo "Backup created successfully: $BACKUP_DIR/instagram_bot_$TIMESTAMP.backup"
  
  # نگهداری 7 پشتیبان آخر
  cd $BACKUP_DIR
  ls -t instagram_bot_*.backup | tail -n +$((MAX_BACKUPS+1)) | xargs rm -f
  
  # ایجاد پشتیبان ساده از جداول مهم در فرمت SQL
  echo "Creating plain SQL backup of critical tables..."
  pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE --table=bot_sessions --table=daily_stats -f "$BACKUP_DIR/critical_tables_$TIMESTAMP.sql"
  
  # ثبت عملیات پشتیبان‌گیری موفق در دیتابیس
  BACKUP_SIZE=$(stat -c %s "$BACKUP_DIR/instagram_bot_$TIMESTAMP.backup")
  psql -h $PGHOST -U $PGUSER -d $PGDATABASE -c "INSERT INTO backup_history (backup_time, backup_path, backup_size, backup_type, status) VALUES (NOW(), '$BACKUP_DIR/instagram_bot_$TIMESTAMP.backup', $BACKUP_SIZE, 'automated', 'success');"
  
  echo "Backup process completed successfully."
else
  echo "Error creating backup."
  # ثبت عملیات پشتیبان‌گیری ناموفق
  psql -h $PGHOST -U $PGUSER -d $PGDATABASE -c "INSERT INTO backup_history (backup_time, backup_path, backup_type, status) VALUES (NOW(), '$BACKUP_DIR/instagram_bot_$TIMESTAMP.backup', 0, 'automated', 'failed');"
fi