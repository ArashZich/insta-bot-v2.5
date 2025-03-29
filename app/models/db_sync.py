# app/models/db_sync.py
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.models.dual_db_manager import db_manager
from app.models.database import BotActivity, UserFollowing, BotSession, DailyStats

# راه‌اندازی لاگر
logger = logging.getLogger("db_sync")


class DatabaseSynchronizer:
    """کلاس همگام‌سازی بین دیتابیس PostgreSQL و SQLite"""

    @staticmethod
    def sync_all_tables():
        """همگام‌سازی همه جداول بین دو دیتابیس"""
        try:
            pg_session, sqlite_session = db_manager.get_both_sessions()

            if not pg_session or not sqlite_session:
                logger.error("هر دو دیتابیس برای همگام‌سازی در دسترس نیستند")
                return False

            # همگام‌سازی جداول
            DatabaseSynchronizer.sync_activities(pg_session, sqlite_session)
            DatabaseSynchronizer.sync_followings(pg_session, sqlite_session)
            DatabaseSynchronizer.sync_sessions(pg_session, sqlite_session)
            DatabaseSynchronizer.sync_daily_stats(pg_session, sqlite_session)

            logger.info("همگام‌سازی همه جداول با موفقیت انجام شد")

            # آزادسازی منابع
            if pg_session:
                pg_session.close()
            if sqlite_session:
                sqlite_session.close()

            return True
        except Exception as e:
            logger.error(f"خطا در همگام‌سازی دیتابیس‌ها: {str(e)}")

            # آزادسازی منابع
            if 'pg_session' in locals() and pg_session:
                pg_session.close()
            if 'sqlite_session' in locals() and sqlite_session:
                sqlite_session.close()

            return False

    @staticmethod
    def sync_activities(pg_session, sqlite_session):
        """همگام‌سازی جدول فعالیت‌ها"""
        try:
            # ابتدا وضعیت دو دیتابیس را بررسی می‌کنیم
            # 1. آخرین فعالیت در PostgreSQL
            pg_last_activity = pg_session.query(BotActivity).order_by(
                BotActivity.created_at.desc()
            ).first()

            # 2. آخرین فعالیت در SQLite
            sqlite_last_activity = sqlite_session.query(BotActivity).order_by(
                BotActivity.created_at.desc()
            ).first()

            # بررسی وضعیت همگام‌سازی
            if not pg_last_activity and sqlite_last_activity:
                # PostgreSQL خالی است اما SQLite داده دارد - انتقال از SQLite به PostgreSQL
                logger.info("انتقال داده‌های فعالیت از SQLite به PostgreSQL")
                sqlite_activities = sqlite_session.query(BotActivity).all()

                for activity in sqlite_activities:
                    # بررسی عدم وجود در PostgreSQL
                    if not pg_session.query(BotActivity).filter(
                        BotActivity.activity_type == activity.activity_type,
                        BotActivity.target_user_id == activity.target_user_id,
                        BotActivity.created_at == activity.created_at
                    ).first():
                        # ایجاد در PostgreSQL
                        new_activity = BotActivity(
                            activity_type=activity.activity_type,
                            target_user_id=activity.target_user_id,
                            target_user_username=activity.target_user_username,
                            target_media_id=activity.target_media_id,
                            status=activity.status,
                            details=activity.details,
                            created_at=activity.created_at
                        )
                        pg_session.add(new_activity)

                pg_session.commit()

            elif pg_last_activity and not sqlite_last_activity:
                # SQLite خالی است اما PostgreSQL داده دارد - انتقال از PostgreSQL به SQLite
                logger.info("انتقال داده‌های فعالیت از PostgreSQL به SQLite")
                pg_activities = pg_session.query(BotActivity).all()

                for activity in pg_activities:
                    # بررسی عدم وجود در SQLite
                    if not sqlite_session.query(BotActivity).filter(
                        BotActivity.activity_type == activity.activity_type,
                        BotActivity.target_user_id == activity.target_user_id,
                        BotActivity.created_at == activity.created_at
                    ).first():
                        # ایجاد در SQLite
                        new_activity = BotActivity(
                            activity_type=activity.activity_type,
                            target_user_id=activity.target_user_id,
                            target_user_username=activity.target_user_username,
                            target_media_id=activity.target_media_id,
                            status=activity.status,
                            details=activity.details,
                            created_at=activity.created_at
                        )
                        sqlite_session.add(new_activity)

                sqlite_session.commit()

            elif pg_last_activity and sqlite_last_activity:
                # هر دو دیتابیس داده دارند - همگام‌سازی دوطرفه
                logger.info("همگام‌سازی دوطرفه داده‌های فعالیت")

                # تعیین دیتابیس با داده‌های جدیدتر
                pg_latest_time = pg_last_activity.created_at
                sqlite_latest_time = sqlite_last_activity.created_at

                if pg_latest_time > sqlite_latest_time:
                    # PostgreSQL داده‌های جدیدتری دارد
                    # انتقال داده‌های جدید به SQLite
                    new_activities = pg_session.query(BotActivity).filter(
                        BotActivity.created_at > sqlite_latest_time
                    ).all()

                    for activity in new_activities:
                        new_activity = BotActivity(
                            activity_type=activity.activity_type,
                            target_user_id=activity.target_user_id,
                            target_user_username=activity.target_user_username,
                            target_media_id=activity.target_media_id,
                            status=activity.status,
                            details=activity.details,
                            created_at=activity.created_at
                        )
                        sqlite_session.add(new_activity)

                    sqlite_session.commit()
                elif sqlite_latest_time > pg_latest_time:
                    # SQLite داده‌های جدیدتری دارد
                    # انتقال داده‌های جدید به PostgreSQL
                    new_activities = sqlite_session.query(BotActivity).filter(
                        BotActivity.created_at > pg_latest_time
                    ).all()

                    for activity in new_activities:
                        new_activity = BotActivity(
                            activity_type=activity.activity_type,
                            target_user_id=activity.target_user_id,
                            target_user_username=activity.target_user_username,
                            target_media_id=activity.target_media_id,
                            status=activity.status,
                            details=activity.details,
                            created_at=activity.created_at
                        )
                        pg_session.add(new_activity)

                    pg_session.commit()

            logger.info("همگام‌سازی جدول فعالیت‌ها با موفقیت انجام شد")
        except Exception as e:
            logger.error(f"خطا در همگام‌سازی جدول فعالیت‌ها: {str(e)}")
            pg_session.rollback()
            sqlite_session.rollback()

    @staticmethod
    def sync_followings(pg_session, sqlite_session):
        """همگام‌سازی جدول فالوینگ‌ها"""
        try:
            # ابتدا وضعیت دو دیتابیس را بررسی می‌کنیم
            # 1. آخرین بروزرسانی در PostgreSQL
            pg_last_following = pg_session.query(UserFollowing).order_by(
                UserFollowing.followed_at.desc()
            ).first()

            # 2. آخرین بروزرسانی در SQLite
            sqlite_last_following = sqlite_session.query(UserFollowing).order_by(
                UserFollowing.followed_at.desc()
            ).first()

            # بررسی وضعیت همگام‌سازی
            if not pg_last_following and sqlite_last_following:
                # PostgreSQL خالی است اما SQLite داده دارد - انتقال از SQLite به PostgreSQL
                logger.info("انتقال داده‌های فالوینگ از SQLite به PostgreSQL")
                sqlite_followings = sqlite_session.query(UserFollowing).all()

                for following in sqlite_followings:
                    # بررسی عدم وجود در PostgreSQL
                    if not pg_session.query(UserFollowing).filter(
                        UserFollowing.user_id == following.user_id
                    ).first():
                        # ایجاد در PostgreSQL
                        new_following = UserFollowing(
                            user_id=following.user_id,
                            username=following.username,
                            followed_at=following.followed_at,
                            unfollowed_at=following.unfollowed_at,
                            is_following=following.is_following,
                            followed_back=following.followed_back
                        )
                        pg_session.add(new_following)

                pg_session.commit()

            elif pg_last_following and not sqlite_last_following:
                # SQLite خالی است اما PostgreSQL داده دارد - انتقال از PostgreSQL به SQLite
                logger.info("انتقال داده‌های فالوینگ از PostgreSQL به SQLite")
                pg_followings = pg_session.query(UserFollowing).all()

                for following in pg_followings:
                    # بررسی عدم وجود در SQLite
                    if not sqlite_session.query(UserFollowing).filter(
                        UserFollowing.user_id == following.user_id
                    ).first():
                        # ایجاد در SQLite
                        new_following = UserFollowing(
                            user_id=following.user_id,
                            username=following.username,
                            followed_at=following.followed_at,
                            unfollowed_at=following.unfollowed_at,
                            is_following=following.is_following,
                            followed_back=following.followed_back
                        )
                        sqlite_session.add(new_following)

                sqlite_session.commit()

            elif pg_last_following and sqlite_last_following:
                # هر دو دیتابیس داده دارند - همگام‌سازی دوطرفه
                logger.info("همگام‌سازی دوطرفه داده‌های فالوینگ")

                # 1. از PostgreSQL به SQLite
                pg_followings = pg_session.query(UserFollowing).all()
                for following in pg_followings:
                    sqlite_following = sqlite_session.query(UserFollowing).filter(
                        UserFollowing.user_id == following.user_id
                    ).first()

                    if not sqlite_following:
                        # رکورد جدید در SQLite ایجاد کنیم
                        new_following = UserFollowing(
                            user_id=following.user_id,
                            username=following.username,
                            followed_at=following.followed_at,
                            unfollowed_at=following.unfollowed_at,
                            is_following=following.is_following,
                            followed_back=following.followed_back
                        )
                        sqlite_session.add(new_following)
                    elif (following.followed_at and sqlite_following.followed_at and
                          following.followed_at > sqlite_following.followed_at):
                        # رکورد PostgreSQL جدیدتر است - SQLite را بروز کنیم
                        sqlite_following.username = following.username
                        sqlite_following.followed_at = following.followed_at
                        sqlite_following.unfollowed_at = following.unfollowed_at
                        sqlite_following.is_following = following.is_following
                        sqlite_following.followed_back = following.followed_back

                # 2. از SQLite به PostgreSQL
                sqlite_followings = sqlite_session.query(UserFollowing).all()
                for following in sqlite_followings:
                    pg_following = pg_session.query(UserFollowing).filter(
                        UserFollowing.user_id == following.user_id
                    ).first()

                    if not pg_following:
                        # رکورد جدید در PostgreSQL ایجاد کنیم
                        new_following = UserFollowing(
                            user_id=following.user_id,
                            username=following.username,
                            followed_at=following.followed_at,
                            unfollowed_at=following.unfollowed_at,
                            is_following=following.is_following,
                            followed_back=following.followed_back
                        )
                        pg_session.add(new_following)
                    elif (following.followed_at and pg_following.followed_at and
                          following.followed_at > pg_following.followed_at):
                        # رکورد SQLite جدیدتر است - PostgreSQL را بروز کنیم
                        pg_following.username = following.username
                        pg_following.followed_at = following.followed_at
                        pg_following.unfollowed_at = following.unfollowed_at
                        pg_following.is_following = following.is_following
                        pg_following.followed_back = following.followed_back

                # ذخیره تغییرات
                sqlite_session.commit()
                pg_session.commit()

            logger.info("همگام‌سازی جدول فالوینگ‌ها با موفقیت انجام شد")
        except Exception as e:
            logger.error(f"خطا در همگام‌سازی جدول فالوینگ‌ها: {str(e)}")
            pg_session.rollback()
            sqlite_session.rollback()

    @staticmethod
    def sync_sessions(pg_session, sqlite_session):
        """همگام‌سازی جدول جلسات ربات"""
        try:
            # ابتدا وضعیت دو دیتابیس را بررسی می‌کنیم
            # 1. آخرین بروزرسانی در PostgreSQL
            pg_last_session = pg_session.query(BotSession).order_by(
                BotSession.updated_at.desc()
            ).first()

            # 2. آخرین بروزرسانی در SQLite
            sqlite_last_session = sqlite_session.query(BotSession).order_by(
                BotSession.updated_at.desc()
            ).first()

            # بررسی وضعیت همگام‌سازی
            if pg_last_session and (not sqlite_last_session or
                                    pg_last_session.updated_at > sqlite_last_session.updated_at):
                # PostgreSQL جلسه جدیدتری دارد - منتقل به SQLite
                logger.info("انتقال داده‌های جلسه از PostgreSQL به SQLite")

                # حذف جلسات قبلی در SQLite
                sqlite_session.query(BotSession).delete()

                # کپی جلسات از PostgreSQL
                pg_sessions = pg_session.query(BotSession).all()
                for session in pg_sessions:
                    new_session = BotSession(
                        username=session.username,
                        session_data=session.session_data,
                        created_at=session.created_at,
                        updated_at=session.updated_at,
                        is_active=session.is_active
                    )
                    sqlite_session.add(new_session)

                sqlite_session.commit()

            elif sqlite_last_session and (not pg_last_session or
                                          sqlite_last_session.updated_at > pg_last_session.updated_at):
                # SQLite جلسه جدیدتری دارد - منتقل به PostgreSQL
                logger.info("انتقال داده‌های جلسه از SQLite به PostgreSQL")

                # حذف جلسات قبلی در PostgreSQL
                pg_session.query(BotSession).delete()

                # کپی جلسات از SQLite
                sqlite_sessions = sqlite_session.query(BotSession).all()
                for session in sqlite_sessions:
                    new_session = BotSession(
                        username=session.username,
                        session_data=session.session_data,
                        created_at=session.created_at,
                        updated_at=session.updated_at,
                        is_active=session.is_active
                    )
                    pg_session.add(new_session)

                pg_session.commit()

            logger.info("همگام‌سازی جدول جلسات ربات با موفقیت انجام شد")
        except Exception as e:
            logger.error(f"خطا در همگام‌سازی جدول جلسات ربات: {str(e)}")
            pg_session.rollback()
            sqlite_session.rollback()

    @staticmethod
    def sync_daily_stats(pg_session, sqlite_session):
        """همگام‌سازی جدول آمار روزانه"""
        try:
            # ابتدا وضعیت دو دیتابیس را بررسی می‌کنیم
            # 1. آمار امروز در PostgreSQL
            today = datetime.now(timezone.utc).date()
            pg_stats = pg_session.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            # 2. آمار امروز در SQLite
            sqlite_stats = sqlite_session.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            # بررسی وضعیت همگام‌سازی
            if pg_stats and not sqlite_stats:
                # فقط PostgreSQL آمار امروز را دارد
                logger.info("انتقال آمار روزانه از PostgreSQL به SQLite")

                new_stats = DailyStats(
                    date=pg_stats.date,
                    follows_count=pg_stats.follows_count,
                    unfollows_count=pg_stats.unfollows_count,
                    likes_count=pg_stats.likes_count,
                    comments_count=pg_stats.comments_count,
                    directs_count=pg_stats.directs_count,
                    story_reactions_count=pg_stats.story_reactions_count,
                    followers_gained=pg_stats.followers_gained,
                    followers_lost=pg_stats.followers_lost
                )
                sqlite_session.add(new_stats)
                sqlite_session.commit()

            elif sqlite_stats and not pg_stats:
                # فقط SQLite آمار امروز را دارد
                logger.info("انتقال آمار روزانه از SQLite به PostgreSQL")

                new_stats = DailyStats(
                    date=sqlite_stats.date,
                    follows_count=sqlite_stats.follows_count,
                    unfollows_count=sqlite_stats.unfollows_count,
                    likes_count=sqlite_stats.likes_count,
                    comments_count=sqlite_stats.comments_count,
                    directs_count=sqlite_stats.directs_count,
                    story_reactions_count=sqlite_stats.story_reactions_count,
                    followers_gained=sqlite_stats.followers_gained,
                    followers_lost=sqlite_stats.followers_lost
                )
                pg_session.add(new_stats)
                pg_session.commit()

            elif pg_stats and sqlite_stats:
                # هر دو دیتابیس آمار را دارند - مقادیر بیشتر را در نظر می‌گیریم
                logger.info("ادغام آمار روزانه بین PostgreSQL و SQLite")

                # ترکیب آمار (مقادیر بیشتر)
                merged_stats = {
                    'follows_count': max(pg_stats.follows_count, sqlite_stats.follows_count),
                    'unfollows_count': max(pg_stats.unfollows_count, sqlite_stats.unfollows_count),
                    'likes_count': max(pg_stats.likes_count, sqlite_stats.likes_count),
                    'comments_count': max(pg_stats.comments_count, sqlite_stats.comments_count),
                    'directs_count': max(pg_stats.directs_count, sqlite_stats.directs_count),
                    'story_reactions_count': max(pg_stats.story_reactions_count, sqlite_stats.story_reactions_count),
                    'followers_gained': max(pg_stats.followers_gained, sqlite_stats.followers_gained),
                    'followers_lost': max(pg_stats.followers_lost, sqlite_stats.followers_lost)
                }

                # بروزرسانی هر دو دیتابیس
                for key, value in merged_stats.items():
                    setattr(pg_stats, key, value)
                    setattr(sqlite_stats, key, value)

                pg_session.commit()
                sqlite_session.commit()

            logger.info("همگام‌سازی جدول آمار روزانه با موفقیت انجام شد")
        except Exception as e:
            logger.error(f"خطا در همگام‌سازی جدول آمار روزانه: {str(e)}")
            pg_session.rollback()
            sqlite_session.rollback()


# تابع کمکی برای اجرای همگام‌سازی
def sync_databases():
    """همگام‌سازی بین دیتابیس‌های PostgreSQL و SQLite"""
    return DatabaseSynchronizer.sync_all_tables()
