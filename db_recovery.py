# db_recovery.py
import time
import logging
import os
from datetime import datetime
from app.models.database import create_tables, engine, Base
from sqlalchemy import text
from pathlib import Path

# تلاش برای import کردن ماژول بکاپ
try:
    from db_backup import check_db_integrity, restore_backup, create_backup
    backup_module_available = True
except ImportError:
    backup_module_available = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_recovery")

# مسیر پوشه بکاپ‌ها
BACKUP_DIR = Path("database_backups")
BACKUP_DIR.mkdir(exist_ok=True)


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
                    result = conn.execute(
                        text("SELECT 1 FROM bot_activities LIMIT 1"))
                    result.close()
                    logger.info("جدول bot_activities موجود است")

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
                logger.info(
                    "تلاش برای بازیابی با استفاده از ماژول پشتیبان‌گیری...")
                if restore_backup():
                    logger.info("بازیابی از بکاپ با موفقیت انجام شد")
                    return
                else:
                    logger.warning(
                        "بازیابی از بکاپ ناموفق بود. تلاش برای ساخت مجدد جداول...")

            # روش 2: بازسازی جداول
            try:
                logger.info("تلاش برای بازسازی جداول...")
                Base.metadata.create_all(bind=engine)
                logger.info("جداول با موفقیت بازسازی شدند")

                # بعد از بازسازی، یک بکاپ بگیر
                if backup_module_available:
                    create_backup()

            except Exception as rebuild_error:
                logger.error(f"خطا در بازسازی جداول: {str(rebuild_error)}")

                # در صورت شکست در بازسازی جداول، تلاش آخر
                logger.warning("تلاش نهایی برای بازیابی...")
                if backup_module_available:
                    if restore_backup():
                        logger.info("بازیابی نهایی از بکاپ با موفقیت انجام شد")
                    else:
                        logger.error("تمام تلاش‌ها برای بازیابی ناموفق بودند")
        else:
            # اگر دیتابیس سالم است، می‌توانیم یک بکاپ بگیریم
            if backup_module_available:
                # هر 12 ساعت یک بکاپ بگیریم (به جای هر بار چک کردن)
                backup_interval = 12 * 3600  # 12 ساعت

                # بررسی آخرین زمان پشتیبان‌گیری
                backup_marker = Path(BACKUP_DIR / "last_backup_time.txt")
                current_time = time.time()
                should_backup = True

                if backup_marker.exists():
                    try:
                        with open(backup_marker, 'r') as f:
                            last_backup_time = float(f.read().strip())
                        if current_time - last_backup_time < backup_interval:
                            should_backup = False
                    except Exception:
                        pass

                if should_backup:
                    logger.info("شروع پشتیبان‌گیری دوره‌ای...")
                    backup_path = create_backup()
                    if backup_path:
                        logger.info(
                            f"پشتیبان‌گیری با موفقیت انجام شد: {backup_path}")
                        # به‌روزرسانی زمان آخرین بکاپ
                        with open(backup_marker, 'w') as f:
                            f.write(str(current_time))

    except Exception as e:
        logger.error(f"خطا در بررسی و بازیابی دیتابیس: {str(e)}")


if __name__ == "__main__":
    # اجرای بررسی در فواصل زمانی منظم
    while True:
        check_db_and_recover()
        time.sleep(600)  # هر 10 دقیقه
