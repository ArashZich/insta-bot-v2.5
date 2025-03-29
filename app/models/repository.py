# app/models/repository.py
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.dual_db_manager import db_manager
from app.models.database import BotActivity, UserFollowing, BotSession, DailyStats

# راه‌اندازی لاگر
logger = logging.getLogger("repository")


class Repository:
    """
    کلاس ریپازیتوری برای عملیات‌های دیتابیس
    این کلاس تضمین می‌کند که همه عملیات‌ها روی هر دو دیتابیس انجام شوند
    """

    @staticmethod
    def create_bot_activity(activity_type, target_user_id, target_user_username, target_media_id=None,
                            status="success", details=None):
        """ایجاد رکورد فعالیت جدید در هر دو دیتابیس"""

        def _create_activity(session, **kwargs):
            activity = BotActivity(
                activity_type=kwargs["activity_type"],
                target_user_id=kwargs["target_user_id"],
                target_user_username=kwargs["target_user_username"],
                target_media_id=kwargs["target_media_id"],
                status=kwargs["status"],
                details=kwargs["details"],
                created_at=datetime.now(timezone.utc)
            )
            session.add(activity)
            return activity

        try:
            activity_id = db_manager.execute_on_both(
                _create_activity,
                activity_type=activity_type,
                target_user_id=target_user_id,
                target_user_username=target_user_username,
                target_media_id=target_media_id,
                status=status,
                details=details
            )
            logger.info(f"فعالیت {activity_type} با موفقیت ثبت شد")
            return activity_id
        except Exception as e:
            logger.error(f"خطا در ثبت فعالیت {activity_type}: {str(e)}")
            return None

    @staticmethod
    def update_daily_stats(stats_dict):
        """به‌روزرسانی آمار روزانه در هر دو دیتابیس"""

        def _update_stats(session, **kwargs):
            today = datetime.now(timezone.utc).date()
            stats = session.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if not stats:
                stats = DailyStats(date=today)
                session.add(stats)

            # به‌روزرسانی فیلدهای مورد نیاز
            for key, value in kwargs["stats_dict"].items():
                if hasattr(stats, key):
                    setattr(stats, key, value)

            return stats

        try:
            result = db_manager.execute_on_both(
                _update_stats, stats_dict=stats_dict)
            logger.info("آمار روزانه با موفقیت به‌روزرسانی شد")
            return result
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی آمار روزانه: {str(e)}")
            return None

    @staticmethod
    def update_or_create_following(user_id, username, is_following=True, followed_back=False):
        """به‌روزرسانی یا ایجاد رکورد فالوینگ در هر دو دیتابیس"""

        def _update_following(session, **kwargs):
            existing_record = session.query(UserFollowing).filter(
                UserFollowing.user_id == kwargs["user_id"]
            ).first()

            if existing_record:
                existing_record.is_following = kwargs["is_following"]
                existing_record.followed_back = kwargs["followed_back"]

                if kwargs["is_following"]:
                    existing_record.followed_at = datetime.now(timezone.utc)
                    existing_record.unfollowed_at = None
                else:
                    existing_record.unfollowed_at = datetime.now(timezone.utc)

                return existing_record
            else:
                following = UserFollowing(
                    user_id=kwargs["user_id"],
                    username=kwargs["username"],
                    is_following=kwargs["is_following"],
                    followed_back=kwargs["followed_back"],
                    followed_at=datetime.now(
                        timezone.utc) if kwargs["is_following"] else None,
                    unfollowed_at=datetime.now(
                        timezone.utc) if not kwargs["is_following"] else None
                )
                session.add(following)
                return following

        try:
            result = db_manager.execute_on_both(
                _update_following,
                user_id=user_id,
                username=username,
                is_following=is_following,
                followed_back=followed_back
            )
            logger.info(
                f"رکورد فالوینگ برای کاربر {username} با موفقیت به‌روزرسانی شد")
            return result
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی رکورد فالوینگ: {str(e)}")
            return None

    @staticmethod
    def save_bot_session(username, session_data, is_active=True):
        """ذخیره اطلاعات جلسه ربات در هر دو دیتابیس"""

        def _save_session(session, **kwargs):
            existing_session = session.query(BotSession).filter(
                BotSession.username == kwargs["username"]
            ).first()

            if existing_session:
                existing_session.session_data = kwargs["session_data"]
                existing_session.is_active = kwargs["is_active"]
                existing_session.updated_at = datetime.now(timezone.utc)
                return existing_session
            else:
                new_session = BotSession(
                    username=kwargs["username"],
                    session_data=kwargs["session_data"],
                    is_active=kwargs["is_active"],
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(new_session)
                return new_session

        try:
            result = db_manager.execute_on_both(
                _save_session,
                username=username,
                session_data=session_data,
                is_active=is_active
            )
            logger.info(f"جلسه ربات برای کاربر {username} با موفقیت ذخیره شد")
            return result
        except Exception as e:
            logger.error(f"خطا در ذخیره جلسه ربات: {str(e)}")
            return None

    @staticmethod
    def get_bot_activities(activity_type=None, status=None, period=None, page=1, size=20):
        """دریافت فعالیت‌های ربات با امکان فیلتر"""
        # این تابع با اولویت از PostgreSQL استفاده می‌کند، در صورت عدم دسترسی از SQLite
        try:
            db = db_manager.get_primary_session()
            query = db.query(BotActivity)

            # اعمال فیلترها
            if activity_type:
                query = query.filter(
                    BotActivity.activity_type == activity_type)

            if status:
                query = query.filter(BotActivity.status == status)

            # فیلتر تاریخ بر اساس دوره
            if period:
                # اینجا بر اساس period دوره زمانی تعیین می‌شود
                # پیاده‌سازی آن شبیه به کد فعلی در routes.py خواهد بود
                pass

            # شمارش کل رکوردهای منطبق
            total = query.count()

            # اعمال صفحه‌بندی
            query = query.order_by(BotActivity.created_at.desc())
            query = query.offset((page - 1) * size).limit(size)

            activities = query.all()
            db.close()

            return {
                "activities": activities,
                "total": total,
                "page": page,
                "size": size
            }
        except Exception as e:
            logger.error(f"خطا در دریافت فعالیت‌های ربات: {str(e)}")
            return {
                "activities": [],
                "total": 0,
                "page": page,
                "size": size
            }

    @staticmethod
    def get_daily_stats():
        """دریافت آمار روزانه"""
        try:
            db = db_manager.get_primary_session()
            today = datetime.now(timezone.utc).date()
            stats = db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if not stats:
                stats = DailyStats(date=today)
                db.add(stats)
                db.commit()

            result = {
                "follows_count": stats.follows_count,
                "unfollows_count": stats.unfollows_count,
                "likes_count": stats.likes_count,
                "comments_count": stats.comments_count,
                "directs_count": stats.directs_count,
                "story_reactions_count": stats.story_reactions_count,
                "followers_gained": stats.followers_gained,
                "followers_lost": stats.followers_lost
            }

            db.close()
            return result
        except Exception as e:
            logger.error(f"خطا در دریافت آمار روزانه: {str(e)}")
            return {
                "follows_count": 0,
                "unfollows_count": 0,
                "likes_count": 0,
                "comments_count": 0,
                "directs_count": 0,
                "story_reactions_count": 0,
                "followers_gained": 0,
                "followers_lost": 0
            }

    @staticmethod
    def sync_databases():
        """همگام‌سازی داده‌ها بین دو دیتابیس در صورت نیاز"""
        # این تابع برای همگام‌سازی دیتابیس‌ها استفاده می‌شود
        # وقتی PostgreSQL بعد از مدتی دوباره در دسترس باشد
        pass
