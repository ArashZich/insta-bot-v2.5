# db_recovery.py
import time
import logging
import os
from datetime import datetime
from app.models.database import create_tables, engine, Base
from sqlalchemy import text
from pathlib import Path

# تنظیمات لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_recovery")

# مسیر پوشه بکاپ‌ها
BACKUP_DIR = Path("database_backups")
BACKUP_DIR.mkdir(exist_ok=True)

# تلاش برای import کردن ماژول بکاپ
try:
    from db_backup import check_db_integrity, restore_backup, create_backup
    backup_module_available = True
except ImportError:
    backup_module_available = False
    logger.warning("ماژول پشتیبان‌گیری در دسترس نیست")


def check_db_and_recover():
    """بررسی سلامت دیتابیس و بازیابی آن در صورت نیاز"""
    try:
        db_healthy = False

        # تست اتصال به دیتابیس
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("اتصال به دیتابیس برقرار است")
                db_healthy = True
        except Exception as conn_error:
            logger.error(f"خطا در اتصال به دیتابیس: {str(conn_error)}")
            db_healthy = False

        # بررسی وجود جداول
        if db_healthy:
            try:
                with engine.connect() as conn:
                    # بررسی وجود جدول bot_activities
                    try:
                        result = conn.execute(
                            text("SELECT 1 FROM bot_activities LIMIT 1"))
                        result.close()
                        logger.info("جدول bot_activities موجود است")
                    except Exception:
                        logger.warning(
                            "جدول bot_activities موجود نیست یا خالی است")
                        db_healthy = False

                    # جداول دیگر نیز چک شوند
                    tables_to_check = ['bot_sessions',
                                       'user_followings', 'daily_stats']
                    for table in tables_to_check:
                        try:
                            result = conn.execute(
                                text(f"SELECT 1 FROM {table} LIMIT 1"))
                            result.close()
                            logger.info(f"جدول {table} موجود است")
                        except Exception:
                            logger.warning(
                                f"جدول {table} موجود نیست یا خالی است")
                            db_healthy = False

            except Exception as table_error:
                logger.warning(f"مشکل در جداول دیتابیس: {str(table_error)}")
                db_healthy = False

        # اگر دیتابیس مشکل دارد، تلاش برای بازیابی
        if not db_healthy:
            logger.warning("دیتابیس سالم نیست. تلاش برای بازیابی...")

            # روش 1: استفاده از ماژول بکاپ اگر در دسترس است
            if backup_module_available:
                # بررسی وجود فایل بکاپ
                backup_files = list(BACKUP_DIR.glob("instagrambot_backup_*.*"))
                if backup_files:
                    logger.info(
                        "تلاش برای بازیابی با استفاده از فایل پشتیبان...")
                    if restore_backup():
                        logger.info("بازیابی از بکاپ با موفقیت انجام شد")
                        return
                    else:
                        logger.warning(
                            "بازیابی از بکاپ ناموفق بود. تلاش برای ساخت مجدد جداول...")
                else:
                    logger.warning(
                        "هیچ فایل پشتیبانی یافت نشد. تلاش برای ساخت مجدد جداول...")

            # روش 2: بازسازی جداول
            try:
                logger.info("تلاش برای بازسازی جداول...")
                Base.metadata.create_all(bind=engine)
                logger.info("جداول با موفقیت بازسازی شدند")

                # بعد از بازسازی، یک بکاپ بگیر
                if backup_module_available:
                    try:
                        backup_file = create_backup()
                        if backup_file:
                            logger.info(
                                f"پشتیبان گیری بعد از بازسازی انجام شد: {backup_file}")
                    except Exception as backup_error:
                        logger.warning(
                            f"خطا در پشتیبان‌گیری بعد از بازسازی: {str(backup_error)}")

            except Exception as rebuild_error:
                logger.error(f"خطا در بازسازی جداول: {str(rebuild_error)}")
        else:
            logger.info("دیتابیس سالم است")

            # یک بکاپ به صورت دوره‌ای بگیر (نه در هر بار چک)
            # این کار را به db_backup.py واگذار می‌کنیم

    except Exception as e:
        logger.error(f"خطا در بررسی و بازیابی دیتابیس: {str(e)}")


if __name__ == "__main__":
    # اجرای بررسی در فواصل زمانی منظم
    while True:
        check_db_and_recover()
        time.sleep(600)  # هر 10 دقیقه
