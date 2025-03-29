# db_recovery.py
import time
import logging
import os
import psycopg2
from sqlalchemy import create_engine, text

# استخراج متغیرهای محیطی برای اتصال به دیتابیس
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
DB_NAME = os.getenv('DB_NAME', 'instagrambot')
DATABASE_URL = os.getenv(
    'DATABASE_URL', f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
SQLITE_FALLBACK = os.getenv('SQLITE_FALLBACK', 'False').lower() == 'true'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_recovery")


def ensure_database_exists():
    """اطمینان از وجود دیتابیس و ایجاد آن در صورت نیاز"""
    # اگر از SQLite استفاده می‌کنیم، نیازی به ایجاد دیتابیس نیست
    if DATABASE_URL.startswith('sqlite') or SQLITE_FALLBACK:
        logger.info("Using SQLite database, no need to create database")
        return True

    try:
        # اتصال به postgres برای بررسی وجود دیتابیس
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname="postgres",  # اتصال به دیتابیس پیش‌فرض
            connect_timeout=30
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # بررسی وجود دیتابیس
        cursor.execute(
            f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'")
        exists = cursor.fetchone()

        if not exists:
            logger.warning(f"دیتابیس {DB_NAME} وجود ندارد. در حال ایجاد...")
            cursor.execute(f"CREATE DATABASE {DB_NAME}")
            logger.info(f"دیتابیس {DB_NAME} با موفقیت ایجاد شد.")
        else:
            logger.info(f"دیتابیس {DB_NAME} از قبل وجود دارد.")

        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"خطا در بررسی/ایجاد دیتابیس: {str(e)}")
        if SQLITE_FALLBACK:
            logger.warning("استفاده از SQLite به عنوان جایگزین")
            return True
        return False


def check_and_create_tables():
    """بررسی وجود جداول و ایجاد آنها در صورت نیاز"""
    try:
        # ایجاد اتصال به دیتابیس
        if DATABASE_URL.startswith('sqlite') or SQLITE_FALLBACK:
            engine = create_engine('sqlite:///instagram_bot.db')
        else:
            engine = create_engine(
                f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

        # تست اتصال
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("اتصال به دیتابیس برقرار است")

        # بررسی وجود جداول
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM bot_activities LIMIT 1"))
                logger.info("جدول bot_activities موجود است")
        except Exception as e:
            logger.warning(f"جداول مورد نیاز وجود ندارند: {str(e)}")
            logger.info("در حال ایجاد جداول...")

            # ایجاد جداول
            from app.models.database import Base
            Base.metadata.create_all(bind=engine)
            logger.info("جداول با موفقیت ایجاد شدند")

        return True
    except Exception as e:
        logger.error(f"خطا در بررسی/ایجاد جداول: {str(e)}")
        return False


def check_db_and_recover():
    """بررسی سلامت دیتابیس و بازیابی آن در صورت نیاز"""
    try:
        # اطمینان از وجود دیتابیس
        db_exists = ensure_database_exists()

        if db_exists:
            # اطمینان از وجود جداول
            tables_exist = check_and_create_tables()

            if tables_exist:
                logger.info(
                    "دیتابیس و جداول با موفقیت بررسی و آماده‌سازی شدند")
                return True

        logger.warning("مشکلاتی در دیتابیس وجود دارد که نیاز به بررسی دارد")
        return False
    except Exception as e:
        logger.error(f"خطا در بررسی و بازیابی دیتابیس: {str(e)}")
        return False


if __name__ == "__main__":
    # اجرای بررسی اولیه
    success = check_db_and_recover()
    if success:
        logger.info("بازیابی دیتابیس با موفقیت انجام شد")
    else:
        logger.error("مشکل در بازیابی دیتابیس")

    # اجرای بررسی در فواصل زمانی منظم
    while True:
        time.sleep(600)  # هر 10 دقیقه
        check_db_and_recover()
