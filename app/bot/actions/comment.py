import random
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError, PleaseWaitFewMinutes, LoginRequired, RateLimitError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_COMMENT_LIMIT
from app.data.responses import COMMENTS
from app.logger import setup_logger
from app.bot.rate_limit import rate_limit_handler

# Configure logging
logger = setup_logger("comment_action")


class CommentAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db
        self.error_count = 0
        self.retry_delay = 45  # تاخیر اولیه برای تلاش مجدد (ثانیه)

    def get_daily_comment_count(self):
        """Get the number of comments for today"""
        try:
            today = datetime.now(timezone.utc).date()
            stats = self.db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if stats:
                return stats.comments_count
            return 0
        except Exception as e:
            logger.error(f"Error getting daily comment count: {str(e)}")
            # در صورت خطا، مقدار محافظه‌کارانه برگردانیم
            return DAILY_COMMENT_LIMIT - 1

    def can_perform_action(self):
        """Check if we can perform a comment action today"""
        comments_count = self.get_daily_comment_count()
        return comments_count < DAILY_COMMENT_LIMIT

    def get_appropriate_comment(self, media_type=None, post_text=None):
        """Get a random appropriate comment based on media type and post content"""
        if not COMMENTS:
            return "👍"

        # Get category based on post content if available
        category = 'general'

        if post_text:
            # Simple keyword matching to determine post category
            post_text = post_text.lower()

            if any(word in post_text for word in ['غذا', 'خوراک', 'رستوران', 'کافه', 'طعم']):
                category = 'food'
            elif any(word in post_text for word in ['سفر', 'گردش', 'طبیعت', 'دریا', 'جنگل', 'کوه']):
                category = 'travel'
            elif any(word in post_text for word in ['خرید', 'فروش', 'تخفیف', 'قیمت', 'مارک']):
                category = 'shopping'
            elif any(word in post_text for word in ['ورزش', 'فوتبال', 'بسکتبال', 'تنیس', 'شنا', 'دو']):
                category = 'sports'
            elif any(word in post_text for word in ['کتاب', 'مطالعه', 'خواندن', 'نویسنده']):
                category = 'books'
            elif any(word in post_text for word in ['فیلم', 'سینما', 'سریال', 'تئاتر', 'هنر']):
                category = 'movies'
            elif any(word in post_text for word in ['موسیقی', 'آهنگ', 'کنسرت', 'خواننده']):
                category = 'music'

        # Select comment from appropriate category if available, otherwise from general
        if category in COMMENTS and COMMENTS[category]:
            comments = COMMENTS[category]
        else:
            comments = COMMENTS.get('general', ["👍", "عالی", "خیلی خوب"])

        return random.choice(comments)

    def comment_on_media(self, media_id, text=None, user_id=None, username=None, retry_count=0):
        """Comment on a specific media by media_id with improved error handling"""
        # بررسی محدودیت نرخ درخواست
        can_proceed, wait_time = rate_limit_handler.can_proceed("comment")
        if not can_proceed:
            logger.info(
                f"Rate limit check suggests waiting {wait_time:.1f} seconds before commenting")
            if wait_time > 0:
                time.sleep(min(wait_time, 60))  # صبر کنیم، حداکثر 60 ثانیه

        try:
            # Get media info if user info not provided
            if not user_id or not username:
                try:
                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("media")

                    media_info = self.client.media_info(media_id)
                    user_id = media_info.user.pk
                    username = media_info.user.username

                    # Get comment text if not provided
                    if not text:
                        caption = media_info.caption_text if media_info.caption_text else ""
                        text = self.get_appropriate_comment(
                            media_info.media_type, caption)
                except Exception as info_error:
                    logger.error(
                        f"Error getting media info: {str(info_error)}")
                    # اگر نتوانستیم اطلاعات را بگیریم، مقادیر پیش‌فرض استفاده کنیم
                    if not user_id:
                        user_id = "unknown"
                    if not username:
                        username = "unknown"
                    if not text:
                        text = self.get_appropriate_comment()
            elif not text:
                text = self.get_appropriate_comment()

            # ثبت درخواست در مدیریت کننده محدودیت
            rate_limit_handler.log_request("comment")

            # Comment on the media
            result = self.client.media_comment(media_id, text)

            if result:
                # ثبت موفقیت در مدیریت کننده محدودیت
                rate_limit_handler.clear_rate_limit()

                # ریست شمارنده خطا
                self.error_count = 0

                # Record the activity
                activity = BotActivity(
                    activity_type="comment",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=media_id,
                    status="success",
                    details=text
                )
                self.db.add(activity)

                # Update daily stats
                today = datetime.now(timezone.utc).date()
                stats = self.db.query(DailyStats).filter(
                    DailyStats.date >= today
                ).first()

                if stats:
                    stats.comments_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        comments_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully commented on media {media_id} of user {username}")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="comment",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=media_id,
                    status="failed",
                    details=f"Comment failed: {text}"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(f"Failed to comment on media {media_id}")
                return False

        except (PleaseWaitFewMinutes, RateLimitError) as e:
            # محدودیت نرخ درخواست
            error_message = str(e)
            logger.warning(
                f"Rate limit hit during comment operation: {error_message}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="comment",
                target_user_id=user_id if user_id else "unknown",
                target_user_username=username if username else "unknown",
                target_media_id=media_id,
                status="failed",
                details=f"Rate limit error: {error_message}, Comment: {text}"
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
                logger.info(
                    f"Will retry commenting after {wait_seconds} seconds")
                # حداکثر 5 دقیقه صبر می‌کنیم
                time.sleep(min(wait_seconds, 300))
                return self.comment_on_media(media_id, text, user_id, username, retry_count + 1)

            return False

        except LoginRequired as e:
            # خطای نیاز به لاگین مجدد
            logger.error(f"Login required during comment operation: {str(e)}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="comment",
                target_user_id=user_id if user_id else "unknown",
                target_user_username=username if username else "unknown",
                target_media_id=media_id,
                status="failed",
                details=f"Login error: {str(e)}, Comment: {text}"
            )
            self.db.add(activity)
            self.db.commit()
            return False

        except ClientError as e:
            # سایر خطاهای کلاینت
            logger.error(f"Error commenting on media {media_id}: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="comment",
                target_user_id=user_id if user_id else "unknown",
                target_user_username=username if username else "unknown",
                target_media_id=media_id,
                status="failed",
                details=f"Error: {str(e)}, Comment: {text}"
            )
            self.db.add(activity)
            self.db.commit()

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

        except Exception as e:
            # سایر خطاهای غیرمنتظره
            logger.error(
                f"Unexpected error commenting on media {media_id}: {str(e)}")

            try:
                # Record the error
                activity = BotActivity(
                    activity_type="comment",
                    target_user_id=user_id if user_id else "unknown",
                    target_user_username=username if username else "unknown",
                    target_media_id=media_id,
                    status="failed",
                    details=f"Unexpected error: {str(e)}, Comment: {text}"
                )
                self.db.add(activity)
                self.db.commit()
            except Exception as db_error:
                logger.error(
                    f"Error recording comment failure: {str(db_error)}")

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

    def comment_on_hashtag_medias(self, hashtag, max_comments=3):
        """Comment on posts with a specific hashtag"""
        if not self.can_perform_action():
            logger.info(f"Daily comment limit reached: {DAILY_COMMENT_LIMIT}")
            return 0

        try:
            # Get medias by hashtag with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("generic")

                # برای پیدا کردن تعداد بیشتری پست، درخواست می‌کنیم
                medias = self.client.hashtag_medias_recent(
                    hashtag, max_comments * 3)

                if not medias:
                    logger.warning(f"No medias found for hashtag #{hashtag}")
                    return 0
            except Exception as e:
                logger.error(
                    f"Error getting hashtag medias for #{hashtag}: {str(e)}")
                return 0

            commented_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)
            time.sleep(random.uniform(5, 10))

            for media in medias[:max_comments * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily comment limit reached during hashtag operation: {DAILY_COMMENT_LIMIT}")
                    break

                # اگر به تعداد کافی کامنت گذاشتیم، خارج شویم
                if commented_count >= max_comments:
                    break

                user_id = media.user.pk
                username = media.user.username
                caption = media.caption_text if media.caption_text else ""

                # Generate appropriate comment
                comment_text = self.get_appropriate_comment(
                    media.media_type, caption)

                # افزودن تأخیر تصادفی بین کامنت‌ها
                if commented_count > 0:
                    delay = random.uniform(45, 90)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next hashtag comment")
                    time.sleep(delay)

                # Comment on the media
                if self.comment_on_media(media.id, comment_text, user_id, username):
                    commented_count += 1

            return commented_count

        except Exception as e:
            logger.error(
                f"Error commenting on hashtag medias for {hashtag}: {str(e)}")
            return 0

    def comment_on_followers_media(self, max_users=2):
        """Comment on posts from users who follow us"""
        if not self.can_perform_action():
            logger.info(f"Daily comment limit reached: {DAILY_COMMENT_LIMIT}")
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

            commented_count = 0
            # Convert to list and shuffle
            follower_ids = list(my_followers.keys())
            random.shuffle(follower_ids)

            # افزودن تأخیر کوتاه قبل از شروع کامنت‌ها
            time.sleep(random.uniform(5, 10))

            for follower_id in follower_ids[:max_users * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily comment limit reached during followers operation: {DAILY_COMMENT_LIMIT}")
                    break

                # اگر به تعداد کافی کامنت گذاشتیم، خارج شویم
                if commented_count >= max_users:
                    break

                # Get user's media
                try:
                    # افزودن تأخیر تصادفی بین پردازش هر فالوئر
                    if commented_count > 0:
                        delay = random.uniform(30, 60)
                        logger.info(
                            f"Waiting {delay:.1f} seconds before processing next follower for comment")
                        time.sleep(delay)

                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("profile")

                    # دریافت مدیای اخیر کاربر
                    medias = self.client.user_medias(follower_id, 5)

                    if not medias:
                        logger.info(
                            f"No media found for follower {follower_id}, skipping")
                        continue

                    # Get a random media
                    media = random.choice(medias)

                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("profile")

                    username = self.client.user_info(follower_id).username
                    caption = media.caption_text if media.caption_text else ""

                    # Generate appropriate comment
                    comment_text = self.get_appropriate_comment(
                        media.media_type, caption)

                    # افزودن تأخیر تصادفی قبل از کامنت
                    delay = random.uniform(45, 90)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before commenting on follower media")
                    time.sleep(delay)

                    # Comment on the media
                    if self.comment_on_media(media.id, comment_text, follower_id, username):
                        commented_count += 1
                except Exception as media_error:
                    logger.warning(
                        f"Could not get media for user {follower_id}: {str(media_error)}")
                    continue

            return commented_count

        except Exception as e:
            logger.error(f"Error commenting on followers media: {str(e)}")
            return 0

    def comment_on_feed_medias(self, max_comments=5):
        """Comment on posts from the user's feed"""
        if not self.can_perform_action():
            logger.info(f"Daily comment limit reached: {DAILY_COMMENT_LIMIT}")
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

            commented_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            # افزودن تأخیر کوتاه قبل از شروع کامنت‌ها
            time.sleep(random.uniform(5, 10))

            for media in medias[:max_comments * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily comment limit reached during feed operation: {DAILY_COMMENT_LIMIT}")
                    break

                # اگر به تعداد کافی کامنت گذاشتیم، خارج شویم
                if commented_count >= max_comments:
                    break

                user_id = media.user.pk
                username = media.user.username
                caption = media.caption_text if media.caption_text else ""

                # Generate appropriate comment
                comment_text = self.get_appropriate_comment(
                    media.media_type, caption)

                # افزودن تأخیر تصادفی بین کامنت‌ها
                if commented_count > 0:
                    delay = random.uniform(45, 90)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next feed comment")
                    time.sleep(delay)

                # Comment on the media
                if self.comment_on_media(media.id, comment_text, user_id, username):
                    commented_count += 1

            return commented_count

        except Exception as e:
            logger.error(f"Error commenting on feed medias: {str(e)}")
            return 0
