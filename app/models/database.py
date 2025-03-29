from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import time
import logging
import os
import psycopg2

from app.config import DATABASE_URL

# Setup logger
logger = logging.getLogger("database")

# Create SQLAlchemy engine with less aggressive retrying and better defaults
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=600,  # کاهش زمان بازیابی کانکشن - هر 10 دقیقه
    pool_size=5,      # کاهش تعداد کانکشن‌ها
    max_overflow=10,   # کاهش حداکثر کانکشن اضافه
    connect_args={'connect_timeout': 15}  # زمان انتظار اتصال
)

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
    max_retries = 5
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
            else:
                logger.error(
                    "Failed to create database tables after multiple attempts")
                return False

    return False


# Function to check database connection health
def check_db_health():
    try:
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("Database connection is healthy")
            return True
    except Exception as e:
        logger.error(f"Database connection is unhealthy: {str(e)}")
        return False
