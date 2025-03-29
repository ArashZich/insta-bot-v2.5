# db_recovery.py
import logging
import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

# تنظیم لاگر
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_recovery")

# استخراج متغیرهای محیطی برای اتصال به دیتابیس
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
DB_NAME = os.getenv('DB_NAME', 'instagrambot')
DATABASE_URL = os.getenv(
    'DATABASE_URL', f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
SQLITE_FALLBACK = os.getenv('SQLITE_FALLBACK', 'False').lower() == 'true'


def check_sqlite_database():
    """بررسی وضعیت دیتابیس SQLite"""
    try:
        # ایجاد موتور SQLite
        sqlite_url = "sqlite:///instagram_bot.db"
        engine = create_engine(sqlite_url)

        # بررسی اتصال
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("اتصال به دیتابیس برقرار است")

        # بررسی وجود جداول
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        required_tables = ["bot_activities", "bot_sessions",
                           "user_followings", "daily_stats"]
        missing_tables = [
            table for table in required_tables if table not in table_names]

        if missing_tables:
            logger.warning(f"جداول مورد نیاز وجود ندارند: {missing_tables}")

            # ایجاد جداول مورد نیاز
            logger.info("در حال ایجاد جداول...")
            from app.models.database import Base
            Base.metadata.create_all(bind=engine)
            logger.info("جداول با موفقیت ایجاد شدند")
        else:
            logger.info("جدول bot_activities موجود است")

        logger.info("دیتابیس و جداول با موفقیت بررسی و آماده‌سازی شدند")
        return True

    except Exception as e:
        logger.error(f"خطا در بررسی دیتابیس SQLite: {str(e)}")
        return False


def recover_database():
    """بازیابی و آماده‌سازی دیتابیس"""
    success = False

    if DATABASE_URL.startswith('sqlite') or SQLITE_FALLBACK:
        logger.info("Using SQLite database, no need to create database")
        success = check_sqlite_database()
    else:
        # اگر به PostgreSQL دسترسی داریم، آن را بررسی می‌کنیم
        # (این قسمت را می‌توان در آینده پیاده‌سازی کرد)
        # در صورت خطا به SQLite فالبک می‌کنیم
        logger.info("Attempting to connect to PostgreSQL...")
        try:
            engine = create_engine(DATABASE_URL)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("PostgreSQL connection successful")
            success = True
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {str(e)}")
            logger.info("Falling back to SQLite")
            success = check_sqlite_database()

    if success:
        logger.info("بازیابی دیتابیس با موفقیت انجام شد")
    else:
        logger.error("بازیابی دیتابیس ناموفق بود")

    return success


if __name__ == "__main__":
    recover_database()
