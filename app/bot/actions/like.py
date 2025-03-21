import random
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError, PleaseWaitFewMinutes, LoginRequired, RateLimitError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_LIKE_LIMIT
from app.logger import setup_logger
from app.bot.rate_limit import rate_limit_handler

# Configure logging
logger = setup_logger("like_action")


class LikeAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db
        self.error_count = 0
        self.retry_delay = 30  # تاخیر اولیه برای تلاش مجدد (ثانیه)

    def get_daily_like_count(self):
        """Get the number of likes for today"""
        try:
            today = datetime.now(timezone.utc).date()
            stats = self.db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if stats:
                return stats.likes_count
            return 0
        except Exception as e:
            logger.error(f"Error getting daily like count: {str(e)}")
            # در صورت خطا، مقدار محافظه‌کارانه برگردانیم
            return DAILY_LIKE_LIMIT - 5

    def can_perform_action(self):
        """Check if we can perform a like action today"""
        likes_count = self.get_daily_like_count()
        return likes_count < DAILY_LIKE_LIMIT

    def like_media(self, media_id, user_id=None, username=None, retry_count=0):
        """Like a specific media by media_id with improved error handling"""
        # بررسی محدودیت نرخ درخواست
        can_proceed, wait_time = rate_limit_handler.can_proceed("like")
        if not can_proceed:
            logger.info(
                f"Rate limit check suggests waiting {wait_time:.1f} seconds before liking")
            if wait_time > 0:
                time.sleep(min(wait_time, 60))  # صبر کنیم، حداکثر 60 ثانیه

        try:
            # اگر اطلاعات کاربر مشخص نیست، آن را دریافت کنیم
            if not user_id or not username:
                try:
                    media_info = self.client.media_info(media_id)
                    user_id = media_info.user.pk
                    username = media_info.user.username
                except Exception as info_error:
                    logger.error(
                        f"Error getting media info: {str(info_error)}")
                    # اگر نتوانستیم اطلاعات را بگیریم، مقادیر پیش‌فرض استفاده کنیم
                    if not user_id:
                        user_id = "unknown"
                    if not username:
                        username = "unknown"

            # ثبت درخواست در مدیریت کننده محدودیت
            rate_limit_handler.log_request("like")

            # انجام لایک
            result = self.client.media_like(media_id)

            if result:
                # ثبت موفقیت در مدیریت کننده محدودیت
                rate_limit_handler.clear_rate_limit()

                # ریست شمارنده خطا
                self.error_count = 0

                # Record the activity
                activity = BotActivity(
                    activity_type="like",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=media_id,
                    status="success"
                )
                self.db.add(activity)

                # Update daily stats
                today = datetime.now(timezone.utc).date()
                stats = self.db.query(DailyStats).filter(
                    DailyStats.date >= today
                ).first()

                if stats:
                    stats.likes_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        likes_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully liked media {media_id} of user {username}")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="like",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=media_id,
                    status="failed",
                    details="Like operation returned False"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(f"Failed to like media {media_id}")
                return False

        except (PleaseWaitFewMinutes, RateLimitError) as e:
            # محدودیت نرخ درخواست
            error_message = str(e)
            logger.warning(
                f"Rate limit hit during like operation: {error_message}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="like",
                target_user_id=user_id if user_id else "unknown",
                target_user_username=username if username else "unknown",
                target_media_id=media_id,
                status="failed",
                details=f"Rate limit error: {error_message}"
            )
            self.db.add(activity)
            self.db.commit()

            # ثبت خطا در مدیریت کننده محدودیت
            wait_seconds = rate_limit_handler.handle_rate_limit_error(
                error_message)

            # افزایش شمارنده خطا
            self.error_count += 1

            # تلاش مجدد در صورت نیاز
            if retry_count < 1:  # حداکثر یک بار تلاش مجدد
                logger.info(f"Will retry liking after {wait_seconds} seconds")
                # حداکثر 5 دقیقه صبر می‌کنیم
                time.sleep(min(wait_seconds, 300))
                return self.like_media(media_id, user_id, username, retry_count + 1)

            return False

        except LoginRequired as e:
            # خطای نیاز به لاگین مجدد
            logger.error(f"Login required during like operation: {str(e)}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="like",
                target_user_id=user_id if user_id else "unknown",
                target_user_username=username if username else "unknown",
                target_media_id=media_id,
                status="failed",
                details=f"Login error: {str(e)}"
            )
            self.db.add(activity)
            self.db.commit()
            return False

        except ClientError as e:
            # سایر خطاهای کلاینت
            logger.error(f"Error liking media {media_id}: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="like",
                target_user_id=user_id if user_id else "unknown",
                target_user_username=username if username else "unknown",
                target_media_id=media_id,
                status="failed",
                details=str(e)
            )
            self.db.add(activity)
            self.db.commit()

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

        except Exception as e:
            # سایر خطاهای غیرمنتظره
            logger.error(f"Unexpected error during like operation: {str(e)}")

            try:
                # Record the error
                activity = BotActivity(
                    activity_type="like",
                    target_user_id=user_id if user_id else "unknown",
                    target_user_username=username if username else "unknown",
                    target_media_id=media_id,
                    status="failed",
                    details=f"Unexpected error: {str(e)}"
                )
                self.db.add(activity)
                self.db.commit()
            except Exception as db_error:
                logger.error(f"Error recording like failure: {str(db_error)}")

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

    def like_user_media(self, user_id, max_likes=3):
        """Like multiple posts from a specific user"""
        if not self.can_perform_action():
            logger.info(f"Daily like limit reached: {DAILY_LIKE_LIMIT}")
            return 0

        try:
            # Get user info
            try:
                user_info = self.client.user_info(user_id)
                username = user_info.username
            except Exception as e:
                logger.error(
                    f"Error getting user info for {user_id}: {str(e)}")
                username = "unknown"

            # Get user medias with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # حداکثر 20 پست اخیر را دریافت کنیم
                medias = self.client.user_medias(user_id, 20)
            except Exception as e:
                logger.error(
                    f"Error getting user medias for {user_id}: {str(e)}")
                return 0

            liked_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            # افزودن تأخیر کوتاه قبل از شروع لایک‌ها
            time.sleep(random.uniform(3, 7))

            for media in medias[:max_likes]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily like limit reached during operation: {DAILY_LIKE_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین لایک‌ها
                if liked_count > 0:
                    delay = random.uniform(15, 45)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next like")
                    time.sleep(delay)

                # Like the media
                if self.like_media(media.id, user_id, username):
                    liked_count += 1

            return liked_count

        except Exception as e:
            logger.error(f"Error liking user medias for {user_id}: {str(e)}")
            return 0

    def like_hashtag_medias(self, hashtag, max_likes=5):
        """Like posts with a specific hashtag"""
        if not self.can_perform_action():
            logger.info(f"Daily like limit reached: {DAILY_LIKE_LIMIT}")
            return 0

        try:
            # Get medias by hashtag with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("generic")

                # برای پیدا کردن تعداد بیشتری پست، درخواست می‌کنیم
                medias = self.client.hashtag_medias_recent(
                    hashtag, max_likes * 3)

                if not medias:
                    logger.warning(f"No medias found for hashtag #{hashtag}")
                    return 0
            except Exception as e:
                logger.error(
                    f"Error getting hashtag medias for #{hashtag}: {str(e)}")
                return 0

            liked_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            # افزودن تأخیر کوتاه قبل از شروع لایک‌ها
            time.sleep(random.uniform(3, 7))

            for media in medias[:max_likes]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily like limit reached during operation: {DAILY_LIKE_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین لایک‌ها
                if liked_count > 0:
                    delay = random.uniform(20, 50)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next hashtag like")
                    time.sleep(delay)

                user_id = media.user.pk
                username = media.user.username

                # Like the media
                if self.like_media(media.id, user_id, username):
                    liked_count += 1

            return liked_count

        except Exception as e:
            logger.error(
                f"Error liking hashtag medias for {hashtag}: {str(e)}")
            return 0

    def like_followers_media(self, max_users=3, posts_per_user=2):
        """Like posts from users who follow us"""
        if not self.can_perform_action():
            logger.info(f"Daily like limit reached: {DAILY_LIKE_LIMIT}")
            return 0

        try:
            # Get my user ID
            try:
                user_id = self.client.user_id
            except Exception as e:
                logger.error(f"Error getting user_id: {str(e)}")
                return 0

            # Get my followers with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالوئرها برای کاهش فشار بر API
                my_followers = self.client.user_followers(user_id, amount=50)

                if not my_followers:
                    logger.warning("No followers found")
                    return 0
            except Exception as e:
                logger.error(f"Error getting followers: {str(e)}")
                return 0

            liked_count = 0
            # Convert to list and shuffle
            follower_ids = list(my_followers.keys())
            random.shuffle(follower_ids)

            for follower_id in follower_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily like limit reached during follower operation: {DAILY_LIKE_LIMIT}")
                    break

                # افزودن تأخیر بین پردازش هر فالوئر
                delay = random.uniform(30, 90)
                logger.info(
                    f"Waiting {delay:.1f} seconds before processing next follower")
                time.sleep(delay)

                # Like user's media
                likes_for_user = self.like_user_media(
                    follower_id, posts_per_user)
                liked_count += likes_for_user

                # اگر نتوانستیم هیچ پستی را لایک کنیم، به فالوئر بعدی برویم
                if likes_for_user == 0:
                    logger.info(
                        f"Could not like any posts for follower {follower_id}, continuing to next follower")
                    continue

            return liked_count

        except Exception as e:
            logger.error(f"Error liking followers media: {str(e)}")
            return 0

    def like_feed_medias(self, max_likes=10):
        """Like posts from the user's feed"""
        if not self.can_perform_action():
            logger.info(f"Daily like limit reached: {DAILY_LIKE_LIMIT}")
            return 0

        try:
            # Get feed medias with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("feed")

                # دریافت پست‌های فید
                feed_items = self.client.get_timeline_feed()
                medias = []

                # Extract medias from feed items
                for item in feed_items:
                    if hasattr(item, 'media_or_ad'):
                        medias.append(item.media_or_ad)

                if not medias:
                    logger.warning("No medias found in feed")
                    return 0
            except Exception as e:
                logger.error(f"Error getting feed medias: {str(e)}")
                return 0

            liked_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            # افزودن تأخیر کوتاه قبل از شروع لایک‌ها
            time.sleep(random.uniform(3, 7))

            for media in medias[:max_likes]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily like limit reached during feed operation: {DAILY_LIKE_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین لایک‌ها
                if liked_count > 0:
                    delay = random.uniform(15, 35)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next feed like")
                    time.sleep(delay)

                user_id = media.user.pk
                username = media.user.username

                # Like the media
                if self.like_media(media.id, user_id, username):
                    liked_count += 1

            return liked_count

        except Exception as e:
            logger.error(f"Error liking feed medias: {str(e)}")
            return 0
