import random
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError, PleaseWaitFewMinutes, LoginRequired, RateLimitError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_DIRECT_LIMIT
from app.data.responses import DIRECT_MESSAGES
from app.logger import setup_logger
from app.bot.rate_limit import rate_limit_handler

# Configure logging
logger = setup_logger("direct_action")


class DirectAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db
        self.error_count = 0
        self.retry_delay = 60  # تاخیر اولیه برای تلاش مجدد (ثانیه)

    def get_daily_direct_count(self):
        """Get the number of direct messages for today"""
        try:
            # ایجاد یک اتصال محلی برای این تابع
            from app.models.database import get_db
            local_db = next(get_db())

            today = datetime.now(timezone.utc).date()
            stats = local_db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if stats:
                return stats.directs_count
            return 0
        except Exception as e:
            logger.error(f"Error getting daily direct count: {str(e)}")
            # در صورت خطا، مقدار محافظه‌کارانه برگردانیم
            return DAILY_DIRECT_LIMIT - 1
        finally:
            # بستن اتصال محلی
            if 'local_db' in locals():
                local_db.close()

    def can_perform_action(self):
        """Check if we can perform a direct message action today"""
        directs_count = self.get_daily_direct_count()
        return directs_count < DAILY_DIRECT_LIMIT

    def get_appropriate_message(self, user_info=None, context=None):
        """Get a random appropriate direct message based on context"""
        if not DIRECT_MESSAGES:
            return "سلام 👋"

        # Get category based on context if available
        category = 'general'

        if context == 'new_follower':
            category = 'welcome'
        elif context == 'engagement':
            category = 'engagement'
        elif context == 'inactive':
            category = 'reconnect'

        # Select message from appropriate category if available, otherwise from general
        if category in DIRECT_MESSAGES and DIRECT_MESSAGES[category]:
            messages = DIRECT_MESSAGES[category]
        else:
            messages = DIRECT_MESSAGES.get('general', ["سلام 👋", "چطوری؟"])

        message = random.choice(messages)

        # Personalize message if user info is available
        if user_info and hasattr(user_info, 'username'):
            username = user_info.username
            message = message.replace("{username}", username)

        return message

    def send_direct_message(self, user_id, text=None, username=None, retry_count=0):
        """Send a direct message to a specific user with improved error handling"""
        # بررسی محدودیت نرخ درخواست
        can_proceed, wait_time = rate_limit_handler.can_proceed("direct")
        if not can_proceed:
            logger.info(
                f"Rate limit check suggests waiting {wait_time:.1f} seconds before sending direct message")
            if wait_time > 0:
                time.sleep(min(wait_time, 120))  # صبر کنیم، حداکثر 2 دقیقه

        try:
            # Get user info if not provided
            if not username:
                try:
                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("profile")

                    user_info = self.client.user_info(user_id)
                    username = user_info.username

                    # Get message text if not provided
                    if not text:
                        text = self.get_appropriate_message(user_info)
                except Exception as info_error:
                    logger.error(f"Error getting user info: {str(info_error)}")
                    username = "unknown"
                    if not text:
                        text = self.get_appropriate_message()
            elif not text:
                text = self.get_appropriate_message()

            # ثبت درخواست در مدیریت کننده محدودیت
            rate_limit_handler.log_request("direct")

            # Send the direct message
            result = self.client.direct_send(text, [user_id])

            if result:
                # ثبت موفقیت در مدیریت کننده محدودیت
                rate_limit_handler.clear_rate_limit()

                # ریست شمارنده خطا
                self.error_count = 0

                # Record the activity
                activity = BotActivity(
                    activity_type="direct",
                    target_user_id=user_id,
                    target_user_username=username,
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
                    stats.directs_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        directs_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully sent direct message to user {username}")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="direct",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="failed",
                    details=f"Direct message failed: {text}"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(
                    f"Failed to send direct message to user {username}")
                return False

        except (PleaseWaitFewMinutes, RateLimitError) as e:
            # محدودیت نرخ درخواست
            error_message = str(e)
            logger.warning(
                f"Rate limit hit during direct message operation: {error_message}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="direct",
                target_user_id=user_id,
                target_user_username=username if username else "unknown",
                status="failed",
                details=f"Rate limit error: {error_message}, Message: {text if text else 'None'}"
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
                    f"Will retry sending direct message after {wait_seconds} seconds")
                # حداکثر 10 دقیقه صبر می‌کنیم
                time.sleep(min(wait_seconds, 600))
                return self.send_direct_message(user_id, text, username, retry_count + 1)

            return False

        except LoginRequired as e:
            # خطای نیاز به لاگین مجدد
            logger.error(
                f"Login required during direct message operation: {str(e)}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="direct",
                target_user_id=user_id,
                target_user_username=username if username else "unknown",
                status="failed",
                details=f"Login error: {str(e)}, Message: {text if text else 'None'}"
            )
            self.db.add(activity)
            self.db.commit()
            return False

        except ClientError as e:
            # سایر خطاهای کلاینت
            logger.error(
                f"Error sending direct message to user {user_id}: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="direct",
                target_user_id=user_id,
                target_user_username=username if username else "unknown",
                status="failed",
                details=f"Error: {str(e)}, Message: {text if text else 'None'}"
            )
            self.db.add(activity)
            self.db.commit()

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

        except Exception as e:
            # سایر خطاهای غیرمنتظره
            logger.error(
                f"Unexpected error sending direct message to user {user_id}: {str(e)}")

            try:
                # Record the error
                activity = BotActivity(
                    activity_type="direct",
                    target_user_id=user_id,
                    target_user_username=username if username else "unknown",
                    status="failed",
                    details=f"Unexpected error: {str(e)}, Message: {text if text else 'None'}"
                )
                self.db.add(activity)
                self.db.commit()
            except Exception as db_error:
                logger.error(
                    f"Error recording direct message failure: {str(db_error)}")

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

    def send_welcome_messages_to_new_followers(self, max_messages=3):
        """Send welcome messages to new followers"""
        if not self.can_perform_action():
            logger.info(
                f"Daily direct message limit reached: {DAILY_DIRECT_LIMIT}")
            return 0

        try:
            # Get my user ID
            try:
                user_id = self.client.user_id
            except Exception as e:
                logger.error(f"Error getting user_id: {str(e)}")
                return 0

            # Get my followers
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالوئرها برای کاهش فشار بر API
                current_followers = self.client.user_followers(
                    user_id, amount=100)
                current_follower_ids = set(current_followers.keys())

                if not current_followers:
                    logger.warning("No followers found")
                    return 0
            except Exception as e:
                logger.error(f"Error getting followers: {str(e)}")
                return 0

            # Get followers we've already sent messages to from activity history
            one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
            try:
                recent_welcome_messages = self.db.query(BotActivity).filter(
                    BotActivity.activity_type == "direct",
                    BotActivity.created_at >= one_day_ago,
                    # Simple way to identify welcome messages
                    BotActivity.details.like("%welcome%")
                ).all()

                already_messaged_ids = {
                    activity.target_user_id for activity in recent_welcome_messages}
            except Exception as e:
                logger.error(
                    f"Error querying recent welcome messages: {str(e)}")
                already_messaged_ids = set()

            # Find new followers we haven't messaged yet
            new_followers = current_follower_ids - already_messaged_ids

            message_count = 0
            # Convert to list and shuffle
            new_follower_list = list(new_followers)
            random.shuffle(new_follower_list)

            # افزودن تأخیر کوتاه قبل از شروع پیام‌ها
            time.sleep(random.uniform(5, 10))

            for follower_id in new_follower_list[:max_messages * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily direct message limit reached during welcome operation: {DAILY_DIRECT_LIMIT}")
                    break

                # اگر به تعداد کافی پیام فرستادیم، خارج شویم
                if message_count >= max_messages:
                    break

                try:
                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("profile")

                    user_info = self.client.user_info(follower_id)
                except Exception as e:
                    logger.error(
                        f"Error getting user info for follower {follower_id}: {str(e)}")
                    continue

                # Get welcome message
                message = self.get_appropriate_message(
                    user_info, 'new_follower')

                # افزودن تأخیر تصادفی بین پیام‌ها
                if message_count > 0:
                    delay = random.uniform(60, 120)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next welcome message")
                    time.sleep(delay)

                # Send direct message
                if self.send_direct_message(follower_id, message, user_info.username):
                    message_count += 1

            return message_count

        except Exception as e:
            logger.error(
                f"Error sending welcome messages to new followers: {str(e)}")
            return 0

    def send_engagement_messages(self, max_messages=2):
        """Send engagement messages to users who have interacted with our content"""
        if not self.can_perform_action():
            logger.info(
                f"Daily direct message limit reached: {DAILY_DIRECT_LIMIT}")
            return 0

        try:
            # Find users who recently liked or commented on our content
            # We can use recent notifications or fetch recent activities on our media

            # For demonstration, let's focus on users who commented on our posts
            # Get my user ID
            try:
                user_id = self.client.user_id
            except Exception as e:
                logger.error(f"Error getting user_id: {str(e)}")
                return 0

            # Get my recent media
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                my_medias = self.client.user_medias(user_id, 5)

                if not my_medias:
                    logger.warning("No media found for my account")
                    return 0
            except Exception as e:
                logger.error(f"Error getting my medias: {str(e)}")
                return 0

            engaged_users = set()

            # Collect users who commented on our recent posts
            for media in my_medias:
                try:
                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("media")

                    comments = self.client.media_comments(media.id)
                    for comment in comments:
                        engaged_users.add(
                            (comment.user.pk, comment.user.username))
                except Exception as e:
                    logger.warning(
                        f"Could not get comments for media {media.id}: {str(e)}")
                    continue

            # Check if we've messaged these users recently (last 7 days)
            one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            try:
                recent_messages = self.db.query(BotActivity).filter(
                    BotActivity.activity_type == "direct",
                    BotActivity.created_at >= one_week_ago
                ).all()

                already_messaged_ids = {
                    activity.target_user_id for activity in recent_messages}
            except Exception as e:
                logger.error(f"Error querying recent messages: {str(e)}")
                already_messaged_ids = set()

            # Filter out users we've messaged recently
            engaged_users = [(user_id, username) for user_id,
                             username in engaged_users if user_id not in already_messaged_ids]

            message_count = 0
            # Shuffle to make it more human-like
            random.shuffle(engaged_users)

            # افزودن تأخیر کوتاه قبل از شروع پیام‌ها
            time.sleep(random.uniform(5, 10))

            for user_id, username in engaged_users[:max_messages * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily direct message limit reached during engagement operation: {DAILY_DIRECT_LIMIT}")
                    break

                # اگر به تعداد کافی پیام فرستادیم، خارج شویم
                if message_count >= max_messages:
                    break

                # Get engagement message
                message = self.get_appropriate_message(None, 'engagement')
                message = message.replace("{username}", username)

                # افزودن تأخیر تصادفی بین پیام‌ها
                if message_count > 0:
                    delay = random.uniform(60, 120)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next engagement message")
                    time.sleep(delay)

                # Send direct message
                if self.send_direct_message(user_id, message, username):
                    message_count += 1

            return message_count

        except Exception as e:
            logger.error(f"Error sending engagement messages: {str(e)}")
            return 0

    def send_inactive_follower_messages(self, days_inactive=30, max_messages=2):
        """Send messages to followers who haven't interacted with us recently"""
        if not self.can_perform_action():
            logger.info(
                f"Daily direct message limit reached: {DAILY_DIRECT_LIMIT}")
            return 0

        try:
            # Get my user ID and followers
            try:
                user_id = self.client.user_id

                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                followers = self.client.user_followers(user_id, amount=100)
                follower_ids = set(followers.keys())

                if not followers:
                    logger.warning("No followers found")
                    return 0
            except Exception as e:
                logger.error(f"Error getting followers: {str(e)}")
                return 0

            # Get users who have interacted with us recently
            threshold_date = datetime.now(
                timezone.utc) - timedelta(days=days_inactive)
            try:
                recent_interactions = self.db.query(BotActivity).filter(
                    BotActivity.created_at >= threshold_date,
                    BotActivity.target_user_id.in_(follower_ids)
                ).all()

                active_user_ids = {
                    activity.target_user_id for activity in recent_interactions}
            except Exception as e:
                logger.error(f"Error querying recent interactions: {str(e)}")
                active_user_ids = set()

            # Find inactive followers
            inactive_followers = follower_ids - active_user_ids

            # Check if we've messaged these users recently (last 30 days)
            try:
                recent_messages = self.db.query(BotActivity).filter(
                    BotActivity.activity_type == "direct",
                    BotActivity.created_at >= threshold_date
                ).all()

                already_messaged_ids = {
                    activity.target_user_id for activity in recent_messages}
            except Exception as e:
                logger.error(f"Error querying recent messages: {str(e)}")
                already_messaged_ids = set()

            # Filter out users we've messaged recently
            inactive_followers = inactive_followers - already_messaged_ids

            message_count = 0
            # Convert to list and shuffle
            inactive_follower_list = list(inactive_followers)
            random.shuffle(inactive_follower_list)

            # افزودن تأخیر کوتاه قبل از شروع پیام‌ها
            time.sleep(random.uniform(5, 10))

            for follower_id in inactive_follower_list[:max_messages * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily direct message limit reached during inactive follower operation: {DAILY_DIRECT_LIMIT}")
                    break

                # اگر به تعداد کافی پیام فرستادیم، خارج شویم
                if message_count >= max_messages:
                    break

                try:
                    # ثبت درخواست در مدیریت کننده محدودیت
                    rate_limit_handler.log_request("profile")

                    user_info = self.client.user_info(follower_id)
                except Exception as e:
                    logger.error(
                        f"Error getting user info for inactive follower {follower_id}: {str(e)}")
                    continue

                # Get reconnect message
                message = self.get_appropriate_message(user_info, 'inactive')

                # افزودن تأخیر تصادفی بین پیام‌ها
                if message_count > 0:
                    delay = random.uniform(60, 120)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next inactive follower message")
                    time.sleep(delay)

                # Send direct message
                if self.send_direct_message(follower_id, message, user_info.username):
                    message_count += 1

            return message_count

        except Exception as e:
            logger.error(f"Error sending inactive follower messages: {str(e)}")
            return 0
