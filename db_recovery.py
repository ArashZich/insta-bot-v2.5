#!/usr/bin/env python3
# db_recovery.py
import time
import logging
import os
import json
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
import psycopg2
from sqlalchemy import create_engine, text

# Add app to path to avoid import issues
sys.path.append('/app')

# تنظیم لاگینگ پیشرفته
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/app/logs/db_recovery.log')
    ]
)
logger = logging.getLogger("db_recovery")

# مسیر پشتیبان‌ها
BACKUP_DIR = Path("/app/backup")
BACKUP_DIR.mkdir(exist_ok=True)


def check_postgres_connection():
    """بررسی مستقیم اتصال به سرور PostgreSQL"""
    try:
        # استفاده از متغیرهای محیطی برای دسترسی به اطلاعات اتصال
        db_host = os.environ.get('DB_HOST', 'postgres')
        db_port = os.environ.get('DB_PORT', '5432')
        # اطمینان از استفاده از postgres به جای root
        db_user = os.environ.get('DB_USER', 'postgres')
        db_password = os.environ.get('DB_PASSWORD', 'postgres')
        db_name = os.environ.get('DB_NAME', 'instagrambot')

        # تلاش برای اتصال مستقیم
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,  # استفاده از کاربر درست
            password=db_password,
            dbname=db_name,
            connect_timeout=10
        )
        conn.close()
        logger.info("Direct PostgreSQL connection successful")
        return True
    except Exception as e:
        logger.error(f"Direct PostgreSQL connection failed: {str(e)}")
        return False


def verify_tables_exist(with_engine=None):
    """بررسی وجود جداول اصلی دیتابیس"""
    try:
        # Import only when needed to avoid circular imports
        from app.models.database import engine as db_engine, SessionLocal

        # استفاده از engine داده شده یا engine پیش‌فرض
        engine_to_use = with_engine if with_engine else db_engine
        session = SessionLocal()

        try:
            # بررسی وجود جداول اصلی
            tables_to_check = ["bot_sessions", "bot_activities",
                               "user_followings", "daily_stats"]
            missing_tables = []

            for table in tables_to_check:
                try:
                    # تلاش برای اجرای یک کوئری ساده روی هر جدول
                    result = session.execute(
                        text(f"SELECT 1 FROM {table} LIMIT 1"))
                    result.close()
                    logger.info(f"Table {table} exists and is accessible")
                except Exception as table_error:
                    logger.warning(
                        f"Issue with table {table}: {str(table_error)}")
                    missing_tables.append(table)

            if missing_tables:
                logger.warning(
                    f"Missing or inaccessible tables: {', '.join(missing_tables)}")
                return False

            logger.info("All required tables exist")
            return True

        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error verifying tables: {str(e)}")
        return False


def create_missing_tables():
    """ایجاد جداول از دست رفته دیتابیس"""
    try:
        # Import only when needed to avoid circular imports
        from app.models.database import create_tables

        logger.info("Attempting to create missing tables...")
        result = create_tables()

        if result:
            logger.info("Successfully created missing tables")
            return True
        else:
            logger.error("Failed to create missing tables")
            return False
    except Exception as e:
        logger.error(f"Error creating missing tables: {str(e)}")
        return False


def backup_critical_data():
    """پشتیبان‌گیری از داده‌های مهم دیتابیس"""
    try:
        # Import only when needed to avoid circular imports
        from app.models.database import SessionLocal, BotSession, DailyStats, UserFollowing

        session = SessionLocal()
        backup_data = {
            "timestamp": datetime.now().isoformat(),
            "bot_sessions": [],
            "daily_stats": [],
            "user_followings": []
        }

        try:
            # استخراج داده‌های نشست
            bot_sessions = session.query(BotSession).all()
            for s in bot_sessions:
                backup_data["bot_sessions"].append({
                    "id": s.id,
                    "username": s.username,
                    "is_active": s.is_active,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None
                })

            # استخراج آمار روزانه
            daily_stats = session.query(DailyStats).order_by(
                DailyStats.date.desc()).limit(10).all()
            for s in daily_stats:
                backup_data["daily_stats"].append({
                    "date": s.date.isoformat() if s.date else None,
                    "follows_count": s.follows_count,
                    "unfollows_count": s.unfollows_count,
                    "likes_count": s.likes_count,
                    "comments_count": s.comments_count,
                    "directs_count": s.directs_count,
                    "story_reactions_count": s.story_reactions_count
                })

            # استخراج داده‌های کاربرانی که فالو شده‌اند
            user_followings = session.query(UserFollowing).filter(
                UserFollowing.is_following == True
            ).limit(100).all()

            for u in user_followings:
                backup_data["user_followings"].append({
                    "user_id": u.user_id,
                    "username": u.username,
                    "is_following": u.is_following,
                    "followed_back": u.followed_back,
                    "followed_at": u.followed_at.isoformat() if u.followed_at else None
                })

            # ذخیره پشتیبان
            filename = f"db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_path = BACKUP_DIR / filename

            with open(backup_path, 'w') as f:
                json.dump(backup_data, f, indent=2)

            logger.info(f"Backup created successfully: {backup_path}")

            # حذف پشتیبان‌های قدیمی (نگهداری 5 نسخه آخر)
            backup_files = sorted(BACKUP_DIR.glob("db_backup_*.json"))
            if len(backup_files) > 5:
                for old_file in backup_files[:-5]:
                    old_file.unlink()
                    logger.info(f"Deleted old backup: {old_file}")

            return True

        finally:
            session.close()

    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        return False


def restore_from_backup():
    """بازیابی داده‌های مهم از آخرین پشتیبان"""
    try:
        backup_files = sorted(BACKUP_DIR.glob("db_backup_*.json"))
        if not backup_files:
            logger.warning("No backup files found for restore")
            return False

        latest_backup = backup_files[-1]
        logger.info(f"Attempting to restore from: {latest_backup}")

        with open(latest_backup, 'r') as f:
            backup_data = json.load(f)

        # Import only when needed to avoid circular imports
        from app.models.database import SessionLocal, BotSession, DailyStats, UserFollowing

        session = SessionLocal()
        try:
            # بازیابی فقط در صورتی که جداول خالی باشند
            if session.query(BotSession).count() == 0 and len(backup_data.get("bot_sessions", [])) > 0:
                logger.info("Restoring bot sessions from backup...")
                for s_data in backup_data["bot_sessions"]:
                    if "username" in s_data:
                        session.add(BotSession(
                            username=s_data["username"],
                            is_active=s_data.get("is_active", True)
                        ))

            # بازیابی آمار روزانه اگر خالی باشد
            if session.query(DailyStats).count() == 0 and len(backup_data.get("daily_stats", [])) > 0:
                logger.info("Restoring daily stats from backup...")
                for s_data in backup_data["daily_stats"]:
                    if s_data.get("date"):
                        date = datetime.fromisoformat(s_data["date"])
                        session.add(DailyStats(
                            date=date,
                            follows_count=s_data.get("follows_count", 0),
                            unfollows_count=s_data.get("unfollows_count", 0),
                            likes_count=s_data.get("likes_count", 0),
                            comments_count=s_data.get("comments_count", 0),
                            directs_count=s_data.get("directs_count", 0),
                            story_reactions_count=s_data.get(
                                "story_reactions_count", 0)
                        ))

            # بازیابی داده‌های فالو اگر خالی باشد
            if session.query(UserFollowing).count() == 0 and len(backup_data.get("user_followings", [])) > 0:
                logger.info("Restoring user followings from backup...")
                for u_data in backup_data["user_followings"]:
                    if "user_id" in u_data and "username" in u_data:
                        followed_at = None
                        if u_data.get("followed_at"):
                            followed_at = datetime.fromisoformat(
                                u_data["followed_at"])

                        session.add(UserFollowing(
                            user_id=u_data["user_id"],
                            username=u_data["username"],
                            is_following=u_data.get("is_following", False),
                            followed_back=u_data.get("followed_back", False),
                            followed_at=followed_at
                        ))

            session.commit()
            logger.info("Restore from backup completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error during restore: {str(e)}")
            session.rollback()
            return False

        finally:
            session.close()

    except Exception as e:
        logger.error(f"Error in restore process: {str(e)}")
        return False


def optimize_database():
    """بهینه‌سازی دیتابیس برای عملکرد بهتر"""
    try:
        # تنظیمات اتصال
        db_host = os.environ.get('DB_HOST', 'postgres')
        db_port = os.environ.get('DB_PORT', '5432')
        db_user = os.environ.get('DB_USER', 'postgres')
        db_password = os.environ.get('DB_PASSWORD', 'postgres')
        db_name = os.environ.get('DB_NAME', 'instagrambot')

        # اتصال مستقیم برای اجرای دستورات بهینه‌سازی
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            dbname=db_name
        )

        # تنظیم حالت autocommit برای اجرای دستورات مدیریتی
        conn.autocommit = True

        with conn.cursor() as cursor:
            logger.info("Running VACUUM ANALYZE to optimize database...")
            cursor.execute("VACUUM ANALYZE")

            # بررسی وجود جداول قبل از reindex
            cursor.execute("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
            """)
            tables = [row[0] for row in cursor.fetchall()]

            # بهینه‌سازی جداول موجود
            for table in tables:
                logger.info(f"Running REINDEX on table {table}...")
                cursor.execute(f"REINDEX TABLE {table}")

        conn.close()
        logger.info("Database optimization completed successfully")
        return True

    except Exception as e:
        logger.error(f"Error optimizing database: {str(e)}")
        return False


def check_db_and_recover():
    """بررسی سلامت دیتابیس و بازیابی آن در صورت نیاز"""
    try:
        logger.info("Starting database health check...")

        # بررسی اتصال مستقیم به دیتابیس
        connection_ok = check_postgres_connection()

        if not connection_ok:
            logger.error("PostgreSQL connection failed, will retry later")
            return False

        # ایجاد پشتیبان از اطلاعات مهم (صرف نظر از نتیجه سایر عملیات)
        backup_critical_data()

        # بررسی وجود جداول
        tables_ok = verify_tables_exist()

        if not tables_ok:
            logger.warning(
                "Tables missing or inaccessible, attempting to create...")
            create_missing_tables()

            # بررسی مجدد پس از تلاش برای ایجاد
            tables_ok = verify_tables_exist()

            if not tables_ok:
                logger.error("Still having issues with database tables")
                return False
            else:
                # تلاش برای بازیابی از پشتیبان
                logger.info(
                    "Tables created successfully, attempting to restore data...")
                restore_from_backup()

        # بهینه‌سازی دیتابیس (هر 24 ساعت)
        last_optimize_marker = BACKUP_DIR / "last_optimize.txt"
        should_optimize = True

        if last_optimize_marker.exists():
            last_time = datetime.fromtimestamp(
                last_optimize_marker.stat().st_mtime)
            hours_since = (datetime.now() - last_time).total_seconds() / 3600

            if hours_since < 24:
                should_optimize = False
                logger.info(
                    f"Skipping optimization (last run: {hours_since:.1f} hours ago)")

        if should_optimize:
            optimize_database()
            # بروزرسانی زمان آخرین بهینه‌سازی
            with open(last_optimize_marker, 'w') as f:
                f.write(datetime.now().isoformat())

        logger.info("Database health check completed successfully")
        return True

    except Exception as e:
        logger.error(f"Error in database health check: {str(e)}")
        logger.error(traceback.format_exc())
        return False


def cleanup_old_logs():
    """پاکسازی لاگ‌های قدیمی برای جلوگیری از پر شدن دیسک"""
    try:
        log_dir = Path("/app/logs")
        if not log_dir.exists():
            return

        # حذف لاگ‌های قدیمی‌تر از 7 روز
        cutoff = datetime.now() - timedelta(days=7)
        count = 0

        for log_file in log_dir.glob("*.log*"):
            if log_file.is_file():
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff:
                    log_file.unlink()
                    count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} old log files")

    except Exception as e:
        logger.error(f"Error cleaning up logs: {str(e)}")


if __name__ == "__main__":
    logger.info("Database recovery service starting")

    # ابتدا یک تأخیر کوتاه داشته باشیم تا سایر سرویس‌ها راه‌اندازی شوند
    time.sleep(10)

    # اطمینان از وجود دایرکتوری‌های ضروری
    os.makedirs("/app/logs", exist_ok=True)
    os.makedirs("/app/backup", exist_ok=True)

    # اولین بار یک بررسی انجام می‌دهیم
    check_db_and_recover()

    interval = 600  # هر 10 دقیقه
    cleanup_interval = 3600 * 24  # پاکسازی لاگ‌ها هر 24 ساعت
    last_cleanup = time.time()

    # اجرای بررسی در فواصل زمانی منظم
    while True:
        try:
            time.sleep(interval)
            check_db_and_recover()

            # پاکسازی لاگ‌های قدیمی
            current_time = time.time()
            if current_time - last_cleanup >= cleanup_interval:
                cleanup_old_logs()
                last_cleanup = current_time

        except KeyboardInterrupt:
            logger.info(
                "Database recovery service stopping due to keyboard interrupt")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            logger.error(traceback.format_exc())
            # افزایش فاصله در صورت بروز خطا
            interval = 900  # 15 دقیقه
            time.sleep(30)  # کمی صبر کنیم و دوباره تلاش کنیم
