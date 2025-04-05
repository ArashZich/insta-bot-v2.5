from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import time
import logging
import os
import psycopg2
import json
import traceback
from pathlib import Path

from app.config import DATABASE_URL

# Setup logger
logger = logging.getLogger("database")

# Global variables at the module level
engine = None
SessionLocal = None

# تعریف مسیر برای نسخه پشتیبان دیتابیس اضطراری
BACKUP_DIR = Path("/app/backup")
BACKUP_DIR.mkdir(exist_ok=True)

# Create SQLAlchemy engine with database creation capability


def get_engine():
    max_retries = 20
    retry_delay = 10  # seconds

    for attempt in range(max_retries):
        try:
            logger.info(
                f"Attempting to connect to database (attempt {attempt+1}/{max_retries})")

            # اول تلاش می‌کنیم مستقیماً به دیتابیس مشخص شده متصل شویم
            engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,  # بررسی اتصال قبل از هر استفاده
                pool_recycle=600,    # بازیابی اتصال‌ها هر 10 دقیقه
                pool_size=5,         # کاهش از 10 به 5 برای کاهش فشار بر دیتابیس
                max_overflow=10,     # کاهش از 20 به 10
                echo=False,
                connect_args={
                    'connect_timeout': 30,  # افزایش تایم‌اوت اتصال
                    'keepalives': 1,        # فعال کردن keepalives برای جلوگیری از قطع شدن اتصال
                    'keepalives_idle': 30,  # ارسال بسته keepalive بعد از 30 ثانیه بدون فعالیت
                    'keepalives_interval': 10,  # فاصله بین بسته‌های keepalive
                    'keepalives_count': 5    # تعداد تلاش‌های مجدد برای keepalive
                }
            )

            # تست اتصال
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            logger.info("Database connection successful")
            return engine

        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            # اضافه کردن stack trace کامل برای اشکال‌زدایی بهتر
            logger.error(traceback.format_exc())

            # اگر خطا مربوط به عدم وجود دیتابیس است، تلاش می‌کنیم آن را ایجاد کنیم
            if "database" in str(e).lower() and ("exist" in str(e).lower() or "does not exist" in str(e).lower()):
                try:
                    logger.info("Trying to create database...")

                    # استخراج اطلاعات اتصال از رشته اتصال
                    db_parts = DATABASE_URL.replace(
                        "postgresql://", "").split("/")

                    if len(db_parts) > 1:
                        db_name = db_parts[1]
                        user_host = db_parts[0].split("@")

                        if len(user_host) > 1:
                            user_pass = user_host[0].split(":")
                            username = user_pass[0]
                            password = user_pass[1] if len(
                                user_pass) > 1 else ""

                            host_port = user_host[1].split(":")
                            host = host_port[0]
                            port = host_port[1] if len(
                                host_port) > 1 else "5432"
                        else:
                            # فرمت مختلف، احتمالاً اتصال بدون رمز عبور
                            username = "postgres"
                            password = ""
                            host_parts = user_host[0].split(":")
                            host = host_parts[0]
                            port = host_parts[1] if len(
                                host_parts) > 1 else "5432"
                    else:
                        # فرمت اشتباه، استفاده از مقادیر پیش‌فرض
                        logger.warning(
                            "Could not parse DATABASE_URL, using default values")
                        db_name = "instagrambot"
                        username = "postgres"
                        password = "postgres"
                        host = "postgres"
                        port = "5432"

                    # اتصال به PostgreSQL بدون مشخص کردن دیتابیس
                    try:
                        postgres_conn = psycopg2.connect(
                            host=host,
                            port=port,
                            user=username,
                            password=password,
                            dbname="postgres",  # اتصال به دیتابیس پیش‌فرض
                            connect_timeout=30
                        )
                        postgres_conn.autocommit = True  # برای اجرای دستور CREATE DATABASE
                    except Exception as conn_error:
                        logger.error(
                            f"Error connecting to postgres database: {str(conn_error)}")
                        # تلاش با کاربر postgres
                        postgres_conn = psycopg2.connect(
                            host=host,
                            port=port,
                            user="postgres",
                            password="postgres",
                            dbname="postgres",
                            connect_timeout=30
                        )
                        postgres_conn.autocommit = True

                    with postgres_conn.cursor() as cursor:
                        # بررسی وجود دیتابیس قبل از ایجاد آن
                        cursor.execute(
                            f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
                        exists = cursor.fetchone()

                        if not exists:
                            cursor.execute(f"CREATE DATABASE {db_name}")
                            logger.info(
                                f"Successfully created database: {db_name}")

                    postgres_conn.close()

                    # کمی صبر می‌کنیم تا دیتابیس کاملاً ایجاد شود
                    time.sleep(5)

                    # حالا باید به دیتابیس جدید متصل شویم
                    engine = create_engine(
                        DATABASE_URL,
                        pool_pre_ping=True,
                        pool_recycle=600,
                        pool_size=5,
                        max_overflow=10,
                        connect_args={
                            'connect_timeout': 30,
                            'keepalives': 1,
                            'keepalives_idle': 30,
                            'keepalives_interval': 10,
                            'keepalives_count': 5
                        }
                    )
                    return engine

                except Exception as create_error:
                    logger.error(
                        f"Error creating database: {str(create_error)}")

            # تلاش برای استفاده از SQLite به عنوان پشتیبان در صورت خطای مکرر PostgreSQL
            if attempt >= max_retries - 3:  # در 3 تلاش آخر
                logger.warning("Attempting to use SQLite as fallback database")
                sqlite_path = "/app/backup/fallback.db"
                try:
                    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
                    # تست اتصال SQLite
                    with sqlite_engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    logger.info(
                        "Successfully connected to SQLite fallback database")
                    return sqlite_engine
                except Exception as sqlite_error:
                    logger.error(
                        f"SQLite fallback also failed: {str(sqlite_error)}")

            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # افزایش تاخیر برای تلاش‌های بعدی
                retry_delay = min(retry_delay * 1.5, 60)  # حداکثر 60 ثانیه
            else:
                logger.error(
                    "Maximum retry attempts reached. Could not connect to database.")
                raise


# تلاش مداوم برای ایجاد و اتصال به دیتابیس
engine = None
for attempt in range(5):  # پنج بار تلاش میکنیم
    try:
        engine = get_engine()
        break  # اگر موفق بود از حلقه خارج میشویم
    except Exception as e:
        logger.error(f"Failed to get engine: {str(e)}")
        time.sleep(10)  # کمی صبر میکنیم و دوباره تلاش میکنیم

# اگر همچنان نتوانستیم موتور ایجاد کنیم، از SQLite به عنوان آخرین راه‌حل استفاده می‌کنیم
if engine is None:
    logger.critical(
        "FATAL ERROR: Could not create or connect to database after multiple attempts")
    # یک موتور SQLite موقت ایجاد می‌کنیم
    logger.warning("Creating SQLite engine as last resort fallback")
    engine = create_engine('sqlite:///app/backup/emergency_fallback.db')

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for SQLAlchemy models
Base = declarative_base()

# Define models


class BotSession(Base):
    __tablename__ = "bot_sessions"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    session_data = Column(Text)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc),
                        onupdate=datetime.now(timezone.utc))
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


# بکاپ‌گیری از دیتابیس
def backup_database_data():
    """ذخیره داده‌های مهم دیتابیس در فایل JSON به عنوان پشتیبان"""
    try:
        backup_data = {
            "bot_sessions": [],
            "daily_stats": [],
            "user_followings": []
        }

        # ایجاد یک جلسه موقت
        db = SessionLocal()

        try:
            # استخراج داده‌های مهم
            sessions = db.query(BotSession).all()
            for session in sessions:
                backup_data["bot_sessions"].append({
                    "username": session.username,
                    "session_data": session.session_data,
                    "is_active": session.is_active
                })

            stats = db.query(DailyStats).all()
            for stat in stats:
                backup_data["daily_stats"].append({
                    "date": stat.date.isoformat() if stat.date else None,
                    "follows_count": stat.follows_count,
                    "unfollows_count": stat.unfollows_count,
                    "likes_count": stat.likes_count,
                    "comments_count": stat.comments_count,
                    "directs_count": stat.directs_count,
                    "story_reactions_count": stat.story_reactions_count,
                    "followers_gained": stat.followers_gained,
                    "followers_lost": stat.followers_lost
                })

            followings = db.query(UserFollowing).all()
            for following in followings:
                backup_data["user_followings"].append({
                    "user_id": following.user_id,
                    "username": following.username,
                    "followed_at": following.followed_at.isoformat() if following.followed_at else None,
                    "unfollowed_at": following.unfollowed_at.isoformat() if following.unfollowed_at else None,
                    "is_following": following.is_following,
                    "followed_back": following.followed_back
                })

            # ذخیره داده‌ها در فایل JSON
            backup_file = BACKUP_DIR / \
                f"db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(backup_file, 'w') as f:
                json.dump(backup_data, f, indent=2)

            # حفظ فقط 5 فایل پشتیبان آخر
            backup_files = sorted(BACKUP_DIR.glob("db_backup_*.json"))
            if len(backup_files) > 5:
                for old_file in backup_files[:-5]:
                    old_file.unlink()

            logger.info(f"Database backup created successfully: {backup_file}")
            return True

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error creating database backup: {str(e)}")
        return False


# بازگرداندن داده‌های پشتیبان در صورت نیاز
def restore_from_backup():
    """بازگرداندن داده‌های دیتابیس از آخرین فایل پشتیبان"""
    try:
        # یافتن آخرین فایل پشتیبان
        backup_files = sorted(BACKUP_DIR.glob("db_backup_*.json"))
        if not backup_files:
            logger.warning("No backup files found")
            return False

        latest_backup = backup_files[-1]
        logger.info(f"Attempting to restore from backup: {latest_backup}")

        # خواندن داده‌های پشتیبان
        with open(latest_backup, 'r') as f:
            backup_data = json.load(f)

        db = SessionLocal()
        try:
            # بازگرداندن نشست‌ها
            if "bot_sessions" in backup_data:
                for session_data in backup_data["bot_sessions"]:
                    existing = db.query(BotSession).filter(
                        BotSession.username == session_data["username"]
                    ).first()

                    if existing:
                        existing.session_data = session_data["session_data"]
                        existing.is_active = session_data["is_active"]
                    else:
                        new_session = BotSession(
                            username=session_data["username"],
                            session_data=session_data["session_data"],
                            is_active=session_data["is_active"]
                        )
                        db.add(new_session)

            # بازگرداندن آمار روزانه
            if "daily_stats" in backup_data:
                for stat_data in backup_data["daily_stats"]:
                    if not stat_data["date"]:
                        continue

                    date = datetime.fromisoformat(stat_data["date"])
                    existing = db.query(DailyStats).filter(
                        DailyStats.date == date
                    ).first()

                    if not existing:
                        new_stat = DailyStats(
                            date=date,
                            follows_count=stat_data.get("follows_count", 0),
                            unfollows_count=stat_data.get(
                                "unfollows_count", 0),
                            likes_count=stat_data.get("likes_count", 0),
                            comments_count=stat_data.get("comments_count", 0),
                            directs_count=stat_data.get("directs_count", 0),
                            story_reactions_count=stat_data.get(
                                "story_reactions_count", 0),
                            followers_gained=stat_data.get(
                                "followers_gained", 0),
                            followers_lost=stat_data.get("followers_lost", 0)
                        )
                        db.add(new_stat)

            # بازگرداندن اطلاعات فالوئینگ‌ها
            if "user_followings" in backup_data:
                for following_data in backup_data["user_followings"]:
                    existing = db.query(UserFollowing).filter(
                        UserFollowing.user_id == following_data["user_id"]
                    ).first()

                    if not existing:
                        new_following = UserFollowing(
                            user_id=following_data["user_id"],
                            username=following_data["username"],
                            followed_at=datetime.fromisoformat(
                                following_data["followed_at"]) if following_data["followed_at"] else None,
                            unfollowed_at=datetime.fromisoformat(
                                following_data["unfollowed_at"]) if following_data["unfollowed_at"] else None,
                            is_following=following_data.get(
                                "is_following", False),
                            followed_back=following_data.get(
                                "followed_back", False)
                        )
                        db.add(new_following)

            db.commit()
            logger.info("Database restored successfully from backup")
            return True

        except Exception as e:
            logger.error(f"Error during database restore: {str(e)}")
            db.rollback()
            return False

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error restoring from backup: {str(e)}")
        return False


# Function to get DB session
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


# Function to create all database tables with retry logic
def create_tables():
    global engine
    global SessionLocal

    max_retries = 10
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            logger.info(
                f"Creating database tables (attempt {attempt+1}/{max_retries})...")
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully")

            # تلاش برای بازگرداندن داده‌ها از پشتیبان در صورت نیاز
            # این کار را فقط در صورتی انجام می‌دهیم که جداول خالی باشند
            db = SessionLocal()
            try:
                # بررسی وجود داده در جدول BotSession
                session_count = db.query(BotSession).count()
                if session_count == 0:
                    # جداول خالی هستند، تلاش برای بازگرداندن از پشتیبان
                    logger.info(
                        "Tables appear empty, attempting to restore from backup...")
                    restore_from_backup()
            finally:
                db.close()

            return True
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")

            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

                # تلاش مجدد برای ایجاد موتور در صورت نیاز
                try:
                    new_engine = get_engine()
                    engine = new_engine
                    SessionLocal = sessionmaker(
                        autocommit=False, autoflush=False, bind=engine)
                except Exception as engine_error:
                    logger.error(
                        f"Error recreating engine: {str(engine_error)}")
            else:
                logger.critical(
                    "FATAL ERROR: Could not create database tables after multiple attempts")
                return False

    return False


# Function to reset all database tables
def reset_tables():
    try:
        logger.info("Resetting database tables...")

        # ایجاد پشتیبان قبل از ریست
        backup_database_data()

        Base.metadata.drop_all(bind=engine)
        result = create_tables()
        if result:
            logger.info("Database tables reset successfully")
            return True
        else:
            logger.error("Failed to reset tables - could not recreate tables")
            return False
    except Exception as e:
        logger.error(f"Error resetting database tables: {str(e)}")
        return False


# تابع بهبود یافته بررسی سلامت دیتابیس
def check_db_health():
    global engine
    global SessionLocal

    try:
        # تست اتصال
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # بررسی دسترسی به جداول با خواندن سطرهای محدود
        db = SessionLocal()
        try:
            # تلاش برای خواندن یک سطر از جداول مختلف
            db.query(BotSession).limit(1).all()
            db.query(BotActivity).limit(1).all()
            db.query(DailyStats).limit(1).all()
            logger.info("Database connection and tables are healthy")

            # ایجاد پشتیبان به صورت دوره‌ای
            # فقط هر 24 ساعت یکبار پشتیبان می‌گیریم (با استفاده از زمان فایل آخرین پشتیبان)
            backup_files = sorted(BACKUP_DIR.glob("db_backup_*.json"))
            should_backup = True

            if backup_files:
                last_backup = backup_files[-1]
                last_backup_time = datetime.fromtimestamp(
                    last_backup.stat().st_mtime)
                time_since_backup = datetime.now() - last_backup_time

                if time_since_backup.total_seconds() < 86400:  # 24 ساعت
                    should_backup = False

            if should_backup:
                logger.info("Creating scheduled database backup...")
                backup_database_data()

            return True

        except Exception as table_error:
            logger.error(f"Database table access error: {str(table_error)}")
            return False
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Database connection is unhealthy: {str(e)}")

        # تلاش برای بازسازی موتور دیتابیس
        try:
            logger.info("Attempting to recreate database engine...")
            new_engine = get_engine()
            engine = new_engine
            SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=engine)
            logger.info("Database engine recreated successfully")

            # تلاش برای ایجاد جداول در صورت نیاز
            create_tables()

            return True
        except Exception as recreate_error:
            logger.error(
                f"Failed to recreate database engine: {str(recreate_error)}")

            # در صورت مشکل جدی، تلاش برای استفاده از دیتابیس پشتیبان
            try:
                logger.warning(
                    "Attempting to switch to SQLite backup database")
                backup_engine = create_engine(
                    'sqlite:///app/backup/emergency_fallback.db')

                # تست اتصال به دیتابیس پشتیبان
                with backup_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))

                # ایجاد جداول در دیتابیس پشتیبان
                Base.metadata.create_all(bind=backup_engine)

                # جایگزینی موتور و جلسه اصلی با نسخه پشتیبان
                engine = backup_engine
                SessionLocal = sessionmaker(
                    autocommit=False, autoflush=False, bind=engine)

                logger.info("Successfully switched to SQLite backup database")

                # بازگرداندن داده‌ها از پشتیبان
                restore_from_backup()

                return True
            except Exception as backup_error:
                logger.critical(
                    f"Failed to switch to backup database: {str(backup_error)}")
                return False
