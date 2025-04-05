#!/usr/bin/env python3
# fix_db_permissions.py
import os
import sys
import psycopg2
import time
import logging

# تنظیم لاگینگ
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("db_fix")


def fix_database_permissions():
    """بررسی و اصلاح مشکلات دسترسی به دیتابیس"""
    try:
        # اطلاعات اتصال
        db_host = os.environ.get('DB_HOST', 'postgres')
        db_port = os.environ.get('DB_PORT', '5432')
        db_user = 'postgres'  # استفاده از کاربر پیش‌فرض postgres
        db_password = os.environ.get('DB_PASSWORD', 'postgres')

        # اتصال به دیتابیس postgres (دیتابیس پیش‌فرض)
        logger.info(f"Connecting to database as postgres user...")
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            dbname="postgres"
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # بررسی وجود دیتابیس instagrambot
        db_name = os.environ.get('DB_NAME', 'instagrambot')
        logger.info(f"Checking if database {db_name} exists...")
        cursor.execute(
            f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
        if cursor.fetchone() is None:
            logger.info(f"Database {db_name} does not exist, creating it...")
            cursor.execute(f"CREATE DATABASE {db_name}")

        conn.close()

        # اتصال به دیتابیس اصلی
        logger.info(f"Connecting to {db_name} database...")
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            dbname=db_name
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # بررسی و ایجاد جداول اصلی
        logger.info("Creating necessary tables if they don't exist...")

        # جدول bot_sessions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_sessions (
            id SERIAL PRIMARY KEY,
            username VARCHAR UNIQUE,
            session_data TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        )
        """)

        # جدول bot_activities
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_activities (
            id SERIAL PRIMARY KEY,
            activity_type VARCHAR,
            target_user_id VARCHAR,
            target_user_username VARCHAR,
            target_media_id VARCHAR,
            status VARCHAR, 
            details TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # جدول user_followings
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_followings (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR,
            username VARCHAR,
            followed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            unfollowed_at TIMESTAMP WITH TIME ZONE,
            is_following BOOLEAN DEFAULT TRUE,
            followed_back BOOLEAN DEFAULT FALSE
        )
        """)

        # جدول daily_stats
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            id SERIAL PRIMARY KEY,
            date TIMESTAMP WITH TIME ZONE UNIQUE,
            follows_count INTEGER DEFAULT 0,
            unfollows_count INTEGER DEFAULT 0, 
            likes_count INTEGER DEFAULT 0,
            comments_count INTEGER DEFAULT 0,
            directs_count INTEGER DEFAULT 0,
            story_reactions_count INTEGER DEFAULT 0,
            followers_gained INTEGER DEFAULT 0,
            followers_lost INTEGER DEFAULT 0
        )
        """)

        conn.close()
        logger.info(
            "Database permissions and tables have been fixed successfully!")
        return True

    except Exception as e:
        logger.error(f"Error fixing database permissions: {str(e)}")
        return False


if __name__ == "__main__":
    print("Starting database permissions fix...")
    # چند بار تلاش می‌کنیم تا مطمئن شویم سرویس دیتابیس آماده است
    for attempt in range(5):
        if fix_database_permissions():
            print("Database fixed successfully!")
            sys.exit(0)
        print(f"Attempt {attempt+1} failed. Waiting 5 seconds before retry...")
        time.sleep(5)

    print("Failed to fix database after multiple attempts")
    sys.exit(1)
