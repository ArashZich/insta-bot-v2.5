# app/models/database.py
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import time
import logging
import os
import psycopg2

from app.config import DATABASE_URL
from app.models.dual_db_manager import db_manager

# Setup logger
logger = logging.getLogger("database")

# استفاده از Base تعریف شده در dual_db_manager
Base = db_manager.Base

# Define models


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


# Function to get DB session - استفاده از get_db موجود در dual_db_manager
def get_db():
    return db_manager.get_db()


# Function to create all database tables with retry logic
def create_tables():
    """ایجاد جداول در هر دو دیتابیس"""
    return db_manager.create_tables()


# Function to check database connection health and recreate if needed
def check_db_health():
    """بررسی سلامت اتصال‌های دیتابیس"""
    pg_healthy, sqlite_healthy = db_manager.check_health()

    # اگر حداقل یکی از دیتابیس‌ها سالم باشد، مشکلی نیست
    if pg_healthy or sqlite_healthy:
        # اگر هر دو سالم باشند، می‌توانیم همگام‌سازی انجام دهیم
        if pg_healthy and sqlite_healthy:
            # TODO: بررسی نیاز به همگام‌سازی
            pass
        return True
    else:
        # هر دو دیتابیس ناسالم هستند - وضعیت بحرانی
        logger.critical("هر دو دیتابیس PostgreSQL و SQLite ناسالم هستند!")
        return False
