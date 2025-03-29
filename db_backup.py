#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import subprocess
import shutil
from datetime import datetime
import glob
import psycopg2
from pathlib import Path

# تنظیمات لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("db_backup")

# مسیر پوشه بکاپ‌ها
BACKUP_DIR = Path("database_backups")
BACKUP_DIR.mkdir(exist_ok=True)

# تعداد بکاپ‌های نگهداری شده
MAX_BACKUPS = 5

# استخراج اطلاعات اتصال از متغیرهای محیطی


def get_db_credentials():
    from os import environ
    return {
        'dbname': environ.get('DB_NAME', 'instagrambot'),
        'user': environ.get('DB_USER', 'postgres'),
        'password': environ.get('DB_PASSWORD', 'postgres'),
        'host': environ.get('DB_HOST', 'postgres'),
        'port': environ.get('DB_PORT', '5432'),
    }


def create_backup():
    """ایجاد بکاپ از دیتابیس"""
    try:
        # تاریخ و زمان فعلی برای نام فایل
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_creds = get_db_credentials()

        backup_file = BACKUP_DIR / f"instagrambot_backup_{timestamp}.sql"

        # ساخت دستور پشتیبان‌گیری
        env = os.environ.copy()
        env['PGPASSWORD'] = db_creds['password']

        # pg_dump
        cmd = [
            'pg_dump',
            '-h', db_creds['host'],
            '-p', db_creds['port'],
            '-U', db_creds['user'],
            '-d', db_creds['dbname'],
            '-f', str(backup_file),
            '--clean',
            '--if-exists'
        ]

        # تلاش برای پشتیبان‌گیری با استفاده از pg_dump
        try:
            logger.info(f"در حال تهیه پشتیبان با استفاده از pg_dump...")
            process = subprocess.run(
                cmd, env=env, check=True, capture_output=True)
            logger.info(f"پشتیبان‌گیری با موفقیت به {backup_file} انجام شد")

        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.warning(f"خطا در اجرای pg_dump: {str(e)}")
            logger.info("تلاش برای پشتیبان‌گیری با استفاده از روش جایگزین...")

            # روش جایگزین - استفاده از psycopg2
            conn = psycopg2.connect(
                dbname=db_creds['dbname'],
                user=db_creds['user'],
                password=db_creds['password'],
                host=db_creds['host'],
                port=db_creds['port']
            )

            backup_data = []
            tables = ['bot_sessions', 'bot_activities',
                      'user_followings', 'daily_stats']

            with conn.cursor() as cursor:
                # پشتیبان‌گیری از ساختار و داده‌های هر جدول
                for table in tables:
                    backup_data.append(f"-- Table: {table}")

                    # دریافت ساختار جدول
                    cursor.execute(
                        f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'")
                    columns = cursor.fetchall()
                    create_stmt = f"CREATE TABLE IF NOT EXISTS {table} (\n"
                    create_stmt += ",\n".join(
                        [f"    {col[0]} {col[1]}" for col in columns])
                    create_stmt += "\n);"
                    backup_data.append(create_stmt)

                    # دریافت داده‌های جدول
                    cursor.execute(f"SELECT * FROM {table}")
                    rows = cursor.fetchall()
                    column_names = [col[0] for col in columns]
                    column_list = ", ".join(column_names)

                    for row in rows:
                        values = []
                        for val in row:
                            if val is None:
                                values.append("NULL")
                            elif isinstance(val, str):
                                values.append(
                                    f"'{val.replace(chr(39), chr(39)+chr(39))}'")
                            elif isinstance(val, datetime):
                                values.append(f"'{val.isoformat()}'")
                            elif isinstance(val, bool):
                                values.append(str(val).lower())
                            else:
                                values.append(str(val))
                        value_list = ", ".join(values)
                        backup_data.append(
                            f"INSERT INTO {table} ({column_list}) VALUES ({value_list});")

            # نوشتن به فایل بکاپ
            with open(backup_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(backup_data))

            logger.info(
                f"پشتیبان‌گیری با روش جایگزین با موفقیت به {backup_file} انجام شد")

        # حذف بکاپ‌های قدیمی اگر تعداد از حد مجاز بیشتر شد
        cleanup_old_backups()

        return str(backup_file)

    except Exception as e:
        logger.error(f"خطا در پشتیبان‌گیری از دیتابیس: {str(e)}")
        return None


def cleanup_old_backups():
    """حذف بکاپ‌های قدیمی اگر تعداد از حد مجاز بیشتر است"""
    try:
        # لیست همه فایل‌های بکاپ به ترتیب تاریخ (قدیمی‌ترین اول)
        backup_files = sorted(BACKUP_DIR.glob(
            "instagrambot_backup_*.sql"), key=os.path.getmtime)

        # حذف بکاپ‌های قدیمی
        while len(backup_files) > MAX_BACKUPS:
            oldest_file = backup_files.pop(0)  # برداشتن قدیمی‌ترین فایل
            os.remove(oldest_file)
            logger.info(f"بکاپ قدیمی حذف شد: {oldest_file}")

    except Exception as e:
        logger.error(f"خطا در حذف بکاپ‌های قدیمی: {str(e)}")


def get_latest_backup():
    """دریافت آخرین بکاپ موجود"""
    try:
        backup_files = sorted(BACKUP_DIR.glob(
            "instagrambot_backup_*.sql"), key=os.path.getmtime, reverse=True)
        if backup_files:
            return str(backup_files[0])
        return None
    except Exception as e:
        logger.error(f"خطا در یافتن آخرین بکاپ: {str(e)}")
        return None


def restore_backup(backup_file=None):
    """بازیابی دیتابیس از فایل بکاپ"""
    try:
        # اگر فایل بکاپ مشخص نشده، از آخرین بکاپ استفاده کن
        if not backup_file:
            backup_file = get_latest_backup()
            if not backup_file:
                logger.error("هیچ فایل بکاپی برای بازیابی یافت نشد")
                return False

        db_creds = get_db_credentials()

        logger.info(f"بازیابی دیتابیس از فایل {backup_file}")

        # تلاش برای بازیابی با pg_restore یا psql
        try:
            env = os.environ.copy()
            env['PGPASSWORD'] = db_creds['password']

            # بررسی پسوند فایل
            if backup_file.endswith('.sql'):
                # استفاده از psql برای بازیابی
                cmd = [
                    'psql',
                    '-h', db_creds['host'],
                    '-p', db_creds['port'],
                    '-U', db_creds['user'],
                    '-d', db_creds['dbname'],
                    '-f', backup_file
                ]
            else:
                # استفاده از pg_restore
                cmd = [
                    'pg_restore',
                    '-h', db_creds['host'],
                    '-p', db_creds['port'],
                    '-U', db_creds['user'],
                    '-d', db_creds['dbname'],
                    '--clean',
                    backup_file
                ]

            process = subprocess.run(
                cmd, env=env, check=True, capture_output=True)
            logger.info("بازیابی دیتابیس با موفقیت انجام شد")

        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.warning(f"خطا در بازیابی با ابزار PostgreSQL: {str(e)}")
            logger.info("تلاش برای بازیابی با استفاده از روش جایگزین...")

            # روش جایگزین - استفاده از psycopg2
            conn = psycopg2.connect(
                dbname=db_creds['dbname'],
                user=db_creds['user'],
                password=db_creds['password'],
                host=db_creds['host'],
                port=db_creds['port']
            )
            conn.autocommit = True

            with open(backup_file, 'r', encoding='utf-8') as f:
                sql_commands = f.read()

            with conn.cursor() as cursor:
                cursor.execute(sql_commands)

            logger.info("بازیابی دیتابیس با روش جایگزین با موفقیت انجام شد")

        return True

    except Exception as e:
        logger.error(f"خطا در بازیابی دیتابیس: {str(e)}")
        return False


def check_db_integrity():
    """بررسی سلامت دیتابیس"""
    try:
        db_creds = get_db_credentials()

        # تلاش برای اتصال به دیتابیس
        conn = psycopg2.connect(
            dbname=db_creds['dbname'],
            user=db_creds['user'],
            password=db_creds['password'],
            host=db_creds['host'],
            port=db_creds['port'],
            connect_timeout=5
        )

        with conn.cursor() as cursor:
            # بررسی وجود جداول اصلی
            tables_to_check = ['bot_sessions', 'bot_activities',
                               'user_followings', 'daily_stats']
            all_tables_exist = True

            for table in tables_to_check:
                cursor.execute(f"SELECT to_regclass('public.{table}')")
                if cursor.fetchone()[0] is None:
                    logger.warning(f"جدول {table} در دیتابیس وجود ندارد")
                    all_tables_exist = False

            # اگر جداول وجود دارند، تست خواندن داده
            if all_tables_exist:
                test_results = []

                for table in tables_to_check:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        test_results.append(True)
                        logger.info(f"جدول {table} دارای {count} رکورد است")
                    except Exception as table_error:
                        logger.warning(
                            f"خطا در خواندن داده از جدول {table}: {str(table_error)}")
                        test_results.append(False)

                # اگر همه تست‌ها موفق بودند
                if all(test_results):
                    logger.info("تمام جداول وجود دارند و قابل خواندن هستند")
                    return True

            # اگر مشکلی در جداول وجود داشت
            return False

    except Exception as e:
        logger.error(f"خطا در بررسی سلامت دیتابیس: {str(e)}")
        return False


def main():
    """اجرای اصلی - پشتیبان‌گیری دوره‌ای"""
    try:
        # چک کردن سلامت دیتابیس
        if not check_db_integrity():
            logger.warning("مشکل در سلامت دیتابیس. تلاش برای بازیابی...")
            if restore_backup():
                logger.info("دیتابیس با موفقیت از بکاپ بازیابی شد")

        # پشتیبان‌گیری
        logger.info("شروع پشتیبان‌گیری دوره‌ای از دیتابیس")
        backup_file = create_backup()
        if backup_file:
            logger.info(f"پشتیبان‌گیری با موفقیت انجام شد: {backup_file}")

    except Exception as e:
        logger.error(f"خطا در اجرای اصلی: {str(e)}")


if __name__ == "__main__":
    interval_hours = 6  # پشتیبان‌گیری هر 6 ساعت

    while True:
        main()
        sleep_time = interval_hours * 3600
        logger.info(f"خواب برای {interval_hours} ساعت تا پشتیبان‌گیری بعدی")
        time.sleep(sleep_time)
