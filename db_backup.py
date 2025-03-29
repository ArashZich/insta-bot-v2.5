#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import subprocess
import shutil
from datetime import datetime
import glob
from pathlib import Path
import sqlite3
from sqlalchemy import create_engine, text
import json

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

# استفاده از تنظیمات موجود در app/config.py


def get_db_connection_string():
    try:
        from app.config import DATABASE_URL
        return DATABASE_URL
    except ImportError:
        # اگر نتوانستیم فایل config را import کنیم، از متغیرهای محیطی استفاده کنیم
        from os import environ
        db_user = environ.get('DB_USER', 'postgres')
        db_password = environ.get('DB_PASSWORD', 'postgres')
        db_host = environ.get('DB_HOST', 'postgres')
        db_port = environ.get('DB_PORT', '5432')
        db_name = environ.get('DB_NAME', 'instagrambot')
        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


def create_backup():
    """ایجاد بکاپ از دیتابیس"""
    try:
        # تاریخ و زمان فعلی برای نام فایل
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"instagrambot_backup_{timestamp}.sql"

        # دریافت رشته اتصال به دیتابیس
        connection_string = get_db_connection_string()

        # استفاده از SQLAlchemy برای بکاپ مستقل از نوع دیتابیس
        try:
            # اگر SQLite است
            if connection_string.startswith('sqlite:'):
                logger.info(
                    "شناسایی دیتابیس SQLite - استفاده از روش مخصوص SQLite")
                db_path = connection_string.replace('sqlite:///', '')

                # فقط کپی فایل SQLite به عنوان بکاپ
                if os.path.exists(db_path):
                    backup_file = BACKUP_DIR / \
                        f"instagrambot_backup_{timestamp}.db"
                    shutil.copy2(db_path, backup_file)
                    logger.info(f"کپی فایل SQLite به {backup_file} انجام شد")

                    # حذف بکاپ‌های قدیمی
                    cleanup_old_backups('.db')
                    return str(backup_file)
                else:
                    logger.error(f"فایل دیتابیس SQLite یافت نشد: {db_path}")
                    return None

            # اگر PostgreSQL است
            elif connection_string.startswith('postgresql:'):
                logger.info(
                    "شناسایی دیتابیس PostgreSQL - استفاده از روش SQLAlchemy")

                # بدون استفاده از pool_size و max_overflow برای سازگاری
                engine = create_engine(connection_string)

                # استخراج اطلاعات جداول و داده‌ها
                tables = ['bot_sessions', 'bot_activities',
                          'user_followings', 'daily_stats']
                backup_data = []

                with engine.connect() as conn:
                    # بررسی وجود جداول
                    for table in tables:
                        try:
                            result = conn.execute(text(
                                f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table}')"))
                            exists = result.scalar()
                            if exists:
                                logger.info(f"استخراج داده از جدول {table}")

                                # دریافت ساختار جدول
                                result = conn.execute(text(
                                    f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'"))
                                columns = result.fetchall()

                                # ایجاد SQL برای ساخت جدول
                                create_stmt = f"-- Table: {table}\n"
                                create_stmt += f"DROP TABLE IF EXISTS {table};\n"
                                create_stmt += f"CREATE TABLE {table} (\n"
                                column_defs = []

                                for col in columns:
                                    col_name = col[0]
                                    col_type = col[1]
                                    column_defs.append(
                                        f"    {col_name} {col_type}")

                                create_stmt += ",\n".join(column_defs)
                                create_stmt += "\n);\n\n"
                                backup_data.append(create_stmt)

                                # دریافت داده‌های جدول
                                result = conn.execute(
                                    text(f"SELECT * FROM {table}"))
                                rows = result.fetchall()

                                if rows:
                                    column_names = [col[0] for col in columns]
                                    column_list = ", ".join(column_names)

                                    for row in rows:
                                        values = []
                                        for i, val in enumerate(row):
                                            if val is None:
                                                values.append("NULL")
                                            elif isinstance(val, str):
                                                # مقادیر رشته‌ای را escapeکن
                                                escaped_val = val.replace(
                                                    "'", "''")
                                                values.append(
                                                    f"'{escaped_val}'")
                                            elif isinstance(val, datetime):
                                                values.append(
                                                    f"'{val.isoformat()}'")
                                            elif isinstance(val, bool):
                                                values.append(str(val).lower())
                                            else:
                                                values.append(str(val))

                                        value_list = ", ".join(values)
                                        backup_data.append(
                                            f"INSERT INTO {table} ({column_list}) VALUES ({value_list});")
                            else:
                                logger.warning(
                                    f"جدول {table} در دیتابیس وجود ندارد")
                        except Exception as table_error:
                            logger.warning(
                                f"خطا در استخراج جدول {table}: {str(table_error)}")

                # نوشتن به فایل بکاپ
                if backup_data:
                    with open(backup_file, 'w', encoding='utf-8') as f:
                        f.write("\n".join(backup_data))

                    logger.info(
                        f"پشتیبان‌گیری با موفقیت به {backup_file} انجام شد")

                    # حذف بکاپ‌های قدیمی
                    cleanup_old_backups('.sql')
                    return str(backup_file)
                else:
                    logger.warning("هیچ داده‌ای برای پشتیبان‌گیری یافت نشد")
                    return None

            # دیتابیس ناشناخته
            else:
                logger.error(f"نوع دیتابیس ناشناخته: {connection_string}")
                return None

        except Exception as e:
            logger.error(f"خطا در پشتیبان‌گیری از دیتابیس: {str(e)}")
            return None

    except Exception as e:
        logger.error(f"خطا در پشتیبان‌گیری از دیتابیس: {str(e)}")
        return None


def cleanup_old_backups(extension='.sql'):
    """حذف بکاپ‌های قدیمی اگر تعداد از حد مجاز بیشتر است"""
    try:
        # لیست همه فایل‌های بکاپ به ترتیب تاریخ (قدیمی‌ترین اول)
        backup_files = sorted(BACKUP_DIR.glob(
            f"instagrambot_backup_*{extension}"), key=os.path.getmtime)

        # حذف بکاپ‌های قدیمی
        while len(backup_files) > MAX_BACKUPS:
            oldest_file = backup_files.pop(0)  # برداشتن قدیمی‌ترین فایل
            try:
                os.remove(oldest_file)
                logger.info(f"بکاپ قدیمی حذف شد: {oldest_file}")
            except Exception as remove_error:
                logger.error(
                    f"خطا در حذف فایل قدیمی {oldest_file}: {str(remove_error)}")

    except Exception as e:
        logger.error(f"خطا در حذف بکاپ‌های قدیمی: {str(e)}")


def get_latest_backup():
    """دریافت آخرین بکاپ موجود"""
    try:
        # بررسی هر دو نوع فایل بکاپ (SQL و SQLite)
        sql_backups = sorted(BACKUP_DIR.glob(
            "instagrambot_backup_*.sql"), key=os.path.getmtime, reverse=True)
        sqlite_backups = sorted(BACKUP_DIR.glob(
            "instagrambot_backup_*.db"), key=os.path.getmtime, reverse=True)

        # ترکیب هر دو لیست و مرتب‌سازی بر اساس زمان تغییر
        all_backups = sql_backups + sqlite_backups
        latest_backups = sorted(
            all_backups, key=os.path.getmtime, reverse=True)

        if latest_backups:
            return str(latest_backups[0])
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

        logger.info(f"بازیابی دیتابیس از فایل {backup_file}")

        # دریافت رشته اتصال به دیتابیس
        connection_string = get_db_connection_string()

        # استفاده از SQLAlchemy برای بازیابی مستقل از نوع دیتابیس
        try:
            # اگر SQLite است
            if connection_string.startswith('sqlite:'):
                db_path = connection_string.replace('sqlite:///', '')

                # اگر فایل بکاپ هم SQLite است، مستقیماً کپی کن
                if backup_file.endswith('.db'):
                    if os.path.exists(db_path):
                        os.remove(db_path)
                    shutil.copy2(backup_file, db_path)
                    logger.info(
                        f"بازیابی SQLite با موفقیت انجام شد: {backup_file} -> {db_path}")
                    return True

                # اگر فایل بکاپ SQL است، آن را import کن
                elif backup_file.endswith('.sql'):
                    # خواندن محتوای SQL
                    with open(backup_file, 'r', encoding='utf-8') as f:
                        sql_commands = f.read()

                    # اتصال به SQLite و اجرای دستورات
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()

                    # تقسیم دستورات SQL و اجرای آنها
                    commands = sql_commands.split(';')
                    for command in commands:
                        command = command.strip()
                        if command:
                            try:
                                cursor.execute(command + ';')
                            except sqlite3.Error as sql_error:
                                logger.warning(
                                    f"خطا در اجرای دستور SQL در SQLite: {str(sql_error)}")

                    conn.commit()
                    conn.close()
                    logger.info(f"بازیابی SQL به SQLite با موفقیت انجام شد")
                    return True

            # اگر PostgreSQL است
            elif connection_string.startswith('postgresql:'):
                # بدون استفاده از pool_size و max_overflow برای سازگاری
                engine = create_engine(connection_string)

                # اگر فایل بکاپ SQL است
                if backup_file.endswith('.sql'):
                    # خواندن محتوای SQL
                    with open(backup_file, 'r', encoding='utf-8') as f:
                        sql_commands = f.read()

                    # اتصال به PostgreSQL و اجرای دستورات
                    with engine.connect() as conn:
                        # تقسیم دستورات SQL و اجرای آنها
                        # اجرای کل اسکریپت به صورت یکجا
                        try:
                            conn.execute(text(sql_commands))
                            conn.commit()
                            logger.info(
                                f"بازیابی SQL به PostgreSQL با موفقیت انجام شد")
                            return True
                        except Exception as sql_error:
                            logger.warning(
                                f"خطا در اجرای SQL: {str(sql_error)}")

                            # سعی می‌کنیم دستورات را به صورت جداگانه اجرا کنیم
                            try:
                                # تقسیم بر اساس ;
                                sql_statements = sql_commands.split(';')
                                for statement in sql_statements:
                                    statement = statement.strip()
                                    if statement:
                                        try:
                                            conn.execute(text(statement))
                                        except Exception as stmt_error:
                                            logger.warning(
                                                f"خطا در اجرای دستور: {str(stmt_error)}")

                                conn.commit()
                                logger.info(
                                    f"بازیابی SQL جداگانه به PostgreSQL با موفقیت انجام شد")
                                return True
                            except Exception as e:
                                logger.error(
                                    f"خطا در بازیابی جداگانه: {str(e)}")
                                return False

                # اگر فایل بکاپ SQLite است، تبدیل کن
                elif backup_file.endswith('.db'):
                    logger.error(
                        "بازیابی فایل SQLite به PostgreSQL پشتیبانی نمی‌شود")
                    return False

            # دیتابیس ناشناخته
            else:
                logger.error(f"نوع دیتابیس ناشناخته: {connection_string}")
                return False

        except Exception as e:
            logger.error(f"خطا در بازیابی دیتابیس: {str(e)}")
            return False

    except Exception as e:
        logger.error(f"خطا در بازیابی دیتابیس: {str(e)}")
        return False


def check_db_integrity():
    """بررسی سلامت دیتابیس"""
    try:
        # دریافت رشته اتصال به دیتابیس
        connection_string = get_db_connection_string()

        # استفاده از SQLAlchemy برای بررسی سلامت مستقل از نوع دیتابیس
        try:
            # بدون استفاده از pool_size و max_overflow برای سازگاری
            engine = create_engine(connection_string)

            # بررسی اتصال به دیتابیس
            with engine.connect() as conn:
                # بررسی وجود جداول اصلی
                tables_to_check = [
                    'bot_sessions', 'bot_activities', 'user_followings', 'daily_stats']
                all_tables_exist = True

                for table in tables_to_check:
                    try:
                        # بررسی وجود جدول
                        if connection_string.startswith('postgresql:'):
                            result = conn.execute(text(
                                f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table}')"))
                            exists = result.scalar()
                        elif connection_string.startswith('sqlite:'):
                            result = conn.execute(
                                text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"))
                            exists = result.scalar() is not None
                        else:
                            logger.error(
                                f"نوع دیتابیس ناشناخته: {connection_string}")
                            return False

                        if exists:
                            logger.info(f"جدول {table} موجود است")
                        else:
                            logger.warning(
                                f"جدول {table} در دیتابیس وجود ندارد")
                            all_tables_exist = False

                    except Exception as table_error:
                        logger.warning(
                            f"خطا در بررسی جدول {table}: {str(table_error)}")
                        all_tables_exist = False

                return all_tables_exist

        except Exception as e:
            logger.error(f"خطا در بررسی سلامت دیتابیس: {str(e)}")
            return False

    except Exception as e:
        logger.error(f"خطا در بررسی سلامت دیتابیس: {str(e)}")
        return False


def main():
    """اجرای اصلی - پشتیبان‌گیری دوره‌ای"""
    try:
        # چک کردن سلامت دیتابیس
        db_healthy = check_db_integrity()

        if not db_healthy:
            logger.warning("مشکل در سلامت دیتابیس. تلاش برای بازیابی...")
            if restore_backup():
                logger.info("دیتابیس با موفقیت از بکاپ بازیابی شد")
            else:
                logger.warning("بازیابی ناموفق بود. ادامه به پشتیبان‌گیری...")

        # پشتیبان‌گیری
        logger.info("شروع پشتیبان‌گیری دوره‌ای از دیتابیس")
        backup_file = create_backup()

        if backup_file:
            logger.info(f"پشتیبان‌گیری با موفقیت انجام شد: {backup_file}")
        else:
            logger.warning("پشتیبان‌گیری ناموفق بود")

    except Exception as e:
        logger.error(f"خطا در اجرای اصلی: {str(e)}")


if __name__ == "__main__":
    interval_hours = 6  # پشتیبان‌گیری هر 6 ساعت

    while True:
        main()
        sleep_time = interval_hours * 3600
        logger.info(f"خواب برای {interval_hours} ساعت تا پشتیبان‌گیری بعدی")
        time.sleep(sleep_time)
