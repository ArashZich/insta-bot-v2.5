# app/models/dual_db_manager.py
import logging
import threading
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base

from app.config import DATABASE_URL

# راه‌اندازی لاگر
logger = logging.getLogger("dual_db_manager")


class DualDBManager:
    """مدیریت همزمان دو دیتابیس PostgreSQL و SQLite"""

    def __init__(self):
        self.pg_engine = None
        self.sqlite_engine = None
        self.pg_session_factory = None
        self.sqlite_session_factory = None
        self.Base = declarative_base()
        self.pg_enabled = True
        self.sqlite_enabled = True
        self.lock = threading.Lock()  # قفل برای عملیات‌های همزمان

        # ایجاد موتورهای دیتابیس
        self._create_engines()

    def _create_engines(self):
        """ایجاد موتورهای دیتابیس با پارامترهای مناسب"""
        try:
            # موتور PostgreSQL
            self.pg_engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=900,
                pool_size=5,
                max_overflow=10,
                connect_args={'connect_timeout': 15}
            )
            self.pg_session_factory = scoped_session(
                sessionmaker(autocommit=False, autoflush=False,
                             bind=self.pg_engine)
            )
            logger.info("موتور PostgreSQL با موفقیت ایجاد شد")
        except Exception as e:
            logger.error(f"خطا در ایجاد موتور PostgreSQL: {str(e)}")
            self.pg_enabled = False

        try:
            # موتور SQLite
            self.sqlite_engine = create_engine(
                'sqlite:///instagram_bot.db',
                connect_args={'check_same_thread': False}
            )
            self.sqlite_session_factory = scoped_session(
                sessionmaker(autocommit=False, autoflush=False,
                             bind=self.sqlite_engine)
            )
            logger.info("موتور SQLite با موفقیت ایجاد شد")
        except Exception as e:
            logger.error(f"خطا در ایجاد موتور SQLite: {str(e)}")
            self.sqlite_enabled = False

    def create_tables(self):
        """ایجاد جداول در هر دو دیتابیس"""
        if self.pg_enabled:
            try:
                self.Base.metadata.create_all(self.pg_engine)
                logger.info("جداول PostgreSQL با موفقیت ایجاد شدند")
            except Exception as e:
                logger.error(f"خطا در ایجاد جداول PostgreSQL: {str(e)}")
                self.pg_enabled = False

        if self.sqlite_enabled:
            try:
                self.Base.metadata.create_all(self.sqlite_engine)
                logger.info("جداول SQLite با موفقیت ایجاد شدند")
            except Exception as e:
                logger.error(f"خطا در ایجاد جداول SQLite: {str(e)}")
                self.sqlite_enabled = False

    def execute_on_both(self, func, *args, **kwargs):
        """اجرای یک تابع روی هر دو دیتابیس به صورت همزمان"""
        pg_result = None
        sqlite_result = None

        with self.lock:
            # اجرا روی PostgreSQL
            if self.pg_enabled:
                try:
                    pg_session = self.pg_session_factory()
                    pg_result = func(pg_session, *args, **kwargs)
                    pg_session.commit()
                except Exception as e:
                    logger.error(f"خطا در اجرای تابع روی PostgreSQL: {str(e)}")
                    pg_session.rollback()
                finally:
                    pg_session.close()

            # اجرا روی SQLite
            if self.sqlite_enabled:
                try:
                    sqlite_session = self.sqlite_session_factory()
                    sqlite_result = func(sqlite_session, *args, **kwargs)
                    sqlite_session.commit()
                except Exception as e:
                    logger.error(f"خطا در اجرای تابع روی SQLite: {str(e)}")
                    sqlite_session.rollback()
                finally:
                    sqlite_session.close()

        # اولویت با نتیجه PostgreSQL است، اگر موجود باشد
        return pg_result if pg_result is not None else sqlite_result

    def get_primary_session(self):
        """دریافت یک session از دیتابیس اصلی (با اولویت PostgreSQL)"""
        if self.pg_enabled:
            return self.pg_session_factory()
        elif self.sqlite_enabled:
            return self.sqlite_session_factory()
        else:
            raise Exception("هیچ دیتابیسی در دسترس نیست")

    def get_both_sessions(self):
        """دریافت session از هر دو دیتابیس به صورت همزمان"""
        pg_session = None
        sqlite_session = None

        if self.pg_enabled:
            pg_session = self.pg_session_factory()

        if self.sqlite_enabled:
            sqlite_session = self.sqlite_session_factory()

        return pg_session, sqlite_session

    def check_health(self):
        """بررسی سلامت اتصال‌های دیتابیس"""
        pg_healthy = False
        sqlite_healthy = False

        # بررسی PostgreSQL
        if self.pg_enabled:
            try:
                connection = self.pg_engine.connect()
                connection.close()
                pg_healthy = True
                logger.info("اتصال PostgreSQL سالم است")
            except Exception as e:
                logger.error(f"اتصال PostgreSQL ناسالم است: {str(e)}")
                self.pg_enabled = False

        # بررسی SQLite
        if self.sqlite_enabled:
            try:
                connection = self.sqlite_engine.connect()
                connection.close()
                sqlite_healthy = True
                logger.info("اتصال SQLite سالم است")
            except Exception as e:
                logger.error(f"اتصال SQLite ناسالم است: {str(e)}")
                self.sqlite_enabled = False

        # اگر PostgreSQL در دسترس نبود، اما SQLite در دسترس بود،
        # تلاش کنیم دوباره PostgreSQL را فعال کنیم
        if not pg_healthy and sqlite_healthy:
            try:
                self.pg_engine = create_engine(
                    DATABASE_URL,
                    pool_pre_ping=True,
                    pool_recycle=900,
                    pool_size=5,
                    max_overflow=10,
                    connect_args={'connect_timeout': 15}
                )
                connection = self.pg_engine.connect()
                connection.close()
                self.pg_session_factory = scoped_session(
                    sessionmaker(autocommit=False, autoflush=False,
                                 bind=self.pg_engine)
                )
                self.pg_enabled = True
                logger.info("اتصال PostgreSQL با موفقیت بازیابی شد")
            except Exception as e:
                logger.error(f"بازیابی اتصال PostgreSQL ناموفق بود: {str(e)}")

        return pg_healthy, sqlite_healthy

    def sync_databases(self):
        """همگام‌سازی داده‌ها بین دو دیتابیس"""
        # این تابع باید بر اساس نیازهای خاص پروژه پیاده‌سازی شود
        # به عنوان مثال، ممکن است بخواهید داده‌های SQLite را به PostgreSQL منتقل کنید
        # وقتی PostgreSQL دوباره در دسترس باشد
        pass


# ایجاد یک نمونه جهانی از مدیریت دیتابیس
db_manager = DualDBManager()

# تابع کمکی برای دریافت یک session


def get_db():
    """میدلور برای دریافت یک session دیتابیس در FastAPI"""
    db = db_manager.get_primary_session()
    try:
        yield db
    except Exception as e:
        logger.error(f"خطای session: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()
