from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import time
import logging
import os
import psycopg2

from app.config import DATABASE_URL

# Setup logger
logger = logging.getLogger("database")

# Global variables at the module level
engine = None
SessionLocal = None

# Create SQLAlchemy engine with database creation capability


def get_engine():
    max_retries = 15
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            logger.info(
                f"Attempting to connect to database (attempt {attempt+1}/{max_retries})")

            # اول تلاش می‌کنیم مستقیماً به دیتابیس مشخص شده متصل شویم
            engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,  # پینگ کردن پیش از استفاده از اتصال
                pool_recycle=1800,  # بازیافت کانکشن‌ها هر 30 دقیقه
                pool_size=10,  # اندازه استخر اتصالات
                max_overflow=20,  # حداکثر اتصال اضافی
                echo=False  # عدم نمایش دستورات SQL
            )

            # تست اتصال
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            logger.info("Database connection successful")
            return engine

        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")

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
                            connect_timeout=10
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
                            connect_timeout=10
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
                    time.sleep(3)

                    # حالا باید به دیتابیس جدید متصل شویم
                    engine = create_engine(
                        DATABASE_URL,
                        pool_pre_ping=True,
                        pool_recycle=1800,
                        pool_size=10,
                        max_overflow=20
                    )
                    return engine

                except Exception as create_error:
                    logger.error(
                        f"Error creating database: {str(create_error)}")

            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(
                    "Maximum retry attempts reached. Could not connect to database.")
                raise


# تلاش مداوم برای ایجاد و اتصال به دیتابیس
engine = None
for _ in range(5):  # پنج بار تلاش میکنیم
    try:
        engine = get_engine()
        break  # اگر موفق بود از حلقه خارج میشویم
    except Exception as e:
        logger.error(f"Failed to get engine: {str(e)}")
        time.sleep(10)  # کمی صبر میکنیم و دوباره تلاش میکنیم

# اگر همچنان نتوانستیم موتور ایجاد کنیم، خطا میدهیم
if engine is None:
    logger.critical(
        "FATAL ERROR: Could not create or connect to database after multiple attempts")
    # به جای توقف برنامه، یک موتور SQLite موقت ایجاد می‌کنیم
    logger.warning("Creating temporary SQLite engine as fallback")
    engine = create_engine('sqlite:///temp_fallback.db')

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for SQLAlchemy models
Base = declarative_base()

# Define models


class BotSession(Base):
    __tablename__ = "bot_sessions"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    session_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)


class UserFollowing(Base):
    __tablename__ = "user_followings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    username = Column(String)
    followed_at = Column(DateTime, default=datetime.utcnow)
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


# Function to check database connection health and recreate if needed
def check_db_health():
    global engine
    global SessionLocal

    try:
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("Database connection is healthy")
            return True
    except Exception as e:
        logger.error(f"Database connection is unhealthy: {str(e)}")

        # Try to recreate engine
        try:
            new_engine = get_engine()
            engine = new_engine
            SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=engine)
            logger.info("Database engine recreated successfully")
            return True
        except Exception as recreate_error:
            logger.error(
                f"Failed to recreate database engine: {str(recreate_error)}")
            return False
