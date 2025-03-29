# db_recovery.py
import time
import logging
from app.models.database import create_tables, engine, Base
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_recovery")


def check_db_and_recover():
    """بررسی سلامت دیتابیس و بازیابی آن در صورت نیاز"""
    try:
        # تست اتصال به دیتابیس
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("اتصال به دیتابیس برقرار است")

        # بررسی وجود جداول
        try:
            with engine.connect() as conn:
                # بررسی وجود جدول bot_activities
                result = conn.execute(
                    text("SELECT 1 FROM bot_activities LIMIT 1"))
                result.close()
                logger.info("جدول bot_activities موجود است")
        except Exception as table_error:
            logger.warning(f"مشکل در جداول دیتابیس: {str(table_error)}")
            logger.info("تلاش برای بازسازی جداول...")

            # ایجاد مجدد جداول
            Base.metadata.create_all(bind=engine)
            logger.info("جداول با موفقیت بازسازی شدند")

    except Exception as e:
        logger.error(f"خطا در بررسی و بازیابی دیتابیس: {str(e)}")


if __name__ == "__main__":
    # اجرای بررسی در فواصل زمانی منظم
    while True:
        check_db_and_recover()
        time.sleep(600)  # هر 10 دقیقه
