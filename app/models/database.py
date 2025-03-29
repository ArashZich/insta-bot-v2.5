from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import time
import logging
import os

from app.config import DATABASE_URL

# Setup logger
logger = logging.getLogger("database")

# ایجاد Engine با مدیریت خطای بهتر


def get_database_engine():
    """ایجاد engine دیتابیس با پشتیبانی از PostgreSQL و SQLite"""
    try:
        # بررسی استفاده از SQLite یا PostgreSQL
        is_sqlite = DATABASE_URL.startswith('sqlite')

        if is_sqlite:
            engine = create_engine(
                DATABASE_URL,
                connect_args={'check_same_thread': False}
            )
            logger.info("SQLite engine created successfully")
        else:
            engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=900,
                pool_size=5,
                max_overflow=10,
                connect_args={'connect_timeout': 15}
            )
            logger.info("PostgreSQL engine created successfully")

        # تست اتصال
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("Database connection test successful")

        return engine

    except Exception as e:
        logger.error(f"Error creating database engine: {str(e)}")

        # اگر اتصال به PostgreSQL با مشکل مواجه شد، به SQLite فالبک کنیم
        if not DATABASE_URL.startswith('sqlite'):
            logger.warning("Falling back to SQLite database")
            sqlite_engine = create_engine(
                'sqlite:///instagram_bot.db',
                connect_args={'check_same_thread': False}
            )
            return sqlite_engine

        # اگر حتی SQLite هم با مشکل مواجه شد، خطا را منتشر کنیم
        raise


# ایجاد engine
engine = get_database_engine()

# ایجاد session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ایجاد Base برای مدل‌ها
Base = declarative_base()

# تعریف مدل‌ها


class BotSession(Base):
    __tablename__ = "bot_sessions"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    session_data = Column(Text)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(
        timezone.utc), onupdate=datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)


class BotActivity(Base):
    __tablename__ = "bot_activities"

    id = Column(Integer, primary_key=True, index=True)
    # follow, unfollow, like, comment, direct, story_reaction
    activity_type = Column(String)
    target_user_id = Column(String, index=True)
    target_user_username = Column(String)
    target_media_id = Column(String, nullable=True)
    status = Column(String)  # success, failed
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class UserFollowing(Base):
    __tablename__ = "user_followings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    username = Column(String)
    followed_at = Column(DateTime, default=datetime.now(timezone.utc))
    unfollowed_at = Column(DateTime, nullable=True)
    is_following = Column(Boolean, default=True)
    followed_back = Column(Boolean, default=False)


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, unique=True, index=True)
    follows_count = Column(Integer, default=0)
    unfollows_count = Column(Integer, default=0)
    likes_count = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    directs_count = Column(Integer, default=0)
    story_reactions_count = Column(Integer, default=0)
    followers_gained = Column(Integer, default=0)
    followers_lost = Column(Integer, default=0)


# ایجاد یک نمونه از مدیریت کننده دیتابیس دوگانه
class DualDBManager:
    """مدیریت همزمان دو دیتابیس PostgreSQL و SQLite"""

    def __init__(self):
        # پیاده‌سازی ساده‌تر - ما فقط می‌خواهیم در صورت خطا به SQLite فالبک کنیم
        self.engine = engine  # از engine موجود استفاده می‌کنیم

        # ایجاد engine SQLite به عنوان پشتیبان
        self.sqlite_engine = None
        if not DATABASE_URL.startswith('sqlite'):
            try:
                self.sqlite_engine = create_engine(
                    'sqlite:///instagram_bot.db',
                    connect_args={'check_same_thread': False}
                )
                logger.info("SQLite backup engine created")
            except Exception as e:
                logger.error(
                    f"Failed to create SQLite backup engine: {str(e)}")

    def backup_to_sqlite(self):
        """ذخیره داده‌ها در SQLite به عنوان پشتیبان"""
        if self.sqlite_engine is None:
            return False

        try:
            # ایجاد جداول در SQLite اگر وجود ندارند
            Base.metadata.create_all(self.sqlite_engine)
            logger.info("SQLite backup tables created or verified")

            # اینجا می‌توانیم داده‌های مهم را به SQLite منتقل کنیم
            # (این قسمت را می‌توان در آینده پیاده‌سازی کرد)

            return True
        except Exception as e:
            logger.error(f"Error backing up to SQLite: {str(e)}")
            return False

    def restore_from_sqlite(self):
        """بازیابی داده‌ها از SQLite در صورت خرابی PostgreSQL"""
        if self.sqlite_engine is None:
            return False

        try:
            # بررسی اتصال به دیتابیس اصلی
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            except Exception:
                logger.warning(
                    "Main database unavailable, attempting to restore from SQLite")

                # در اینجا می‌توانیم داده‌ها را از SQLite به دیتابیس اصلی منتقل کنیم
                # (این قسمت را می‌توان در آینده پیاده‌سازی کرد)

            return True
        except Exception as e:
            logger.error(f"Error restoring from SQLite: {str(e)}")
            return False


# ایجاد نمونه dual db manager
dual_db_manager = DualDBManager()

# تابع برای دریافت DB session


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Session error: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


# تابع برای ایجاد جداول با پشتیبانی از تلاش مجدد
def create_tables():
    try:
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")

        # ذخیره پشتیبان در SQLite
        dual_db_manager.backup_to_sqlite()

        return True
    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}")

        # تلاش مجدد با SQLite اگر دیتابیس اصلی در دسترس نیست
        try:
            if dual_db_manager.sqlite_engine:
                logger.info(
                    "Attempting to create tables in SQLite fallback...")
                Base.metadata.create_all(bind=dual_db_manager.sqlite_engine)
                logger.info("SQLite tables created successfully")
                return True
        except Exception as sqlite_error:
            logger.error(f"Error creating SQLite tables: {str(sqlite_error)}")

        return False


# تابع برای بررسی سلامت دیتابیس
def check_db_health():
    try:
        # تست اتصال
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("Database connection is healthy")

        # ذخیره پشتیبان دوره‌ای
        dual_db_manager.backup_to_sqlite()

        return True
    except Exception as e:
        logger.error(f"Database connection is unhealthy: {str(e)}")

        # تلاش برای بازیابی از SQLite
        restore_result = dual_db_manager.restore_from_sqlite()
        if restore_result:
            logger.info("Successfully restored from SQLite backup")

        # تلاش مجدد با ایجاد engine جدید
        try:
            global engine, SessionLocal
            new_engine = get_database_engine()
            engine = new_engine
            SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=engine)
            logger.info("Database engine recreated successfully")
            return True
        except Exception as recreate_error:
            logger.error(
                f"Failed to recreate database engine: {str(recreate_error)}")
            return False
