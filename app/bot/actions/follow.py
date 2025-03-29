import random
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import UserNotFound, ClientError, PleaseWaitFewMinutes, LoginRequired, RateLimitError

from app.models.database import BotActivity, UserFollowing, DailyStats
from app.config import DAILY_FOLLOW_LIMIT
from app.logger import setup_logger
from app.bot.rate_limit import rate_limit_handler

# Configure logging
logger = setup_logger("follow_action")


class FollowAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db
        self.error_count = 0
        self.retry_delay = 30  # تاخیر اولیه برای تلاش مجدد (ثانیه)

    def get_daily_follow_count(self):
        """Get the number of follows for today"""
        try:
            today = datetime.now(timezone.utc).date()
            stats = self.db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if stats:
                return stats.follows_count
            return 0
        except Exception as e:
            logger.error(f"Error getting daily follow count: {str(e)}")
            # در صورت خطا، مقدار محافظه‌کارانه برگردانیم
            return DAILY_FOLLOW_LIMIT - 2

    def can_perform_action(self):
        """Check if we can perform a follow action today"""
        follows_count = self.get_daily_follow_count()
        return follows_count < DAILY_FOLLOW_LIMIT

    def follow_user(self, user_id, retry_count=0):
        """Follow a specific user by user_id with improved error handling"""
        # بررسی محدودیت نرخ درخواست
        can_proceed, wait_time = rate_limit_handler.can_proceed("follow")
        if not can_proceed:
            logger.info(
                f"Rate limit check suggests waiting {wait_time:.1f} seconds before following")
            if wait_time > 0:
                time.sleep(min(wait_time, 60))  # صبر کنیم، حداکثر 60 ثانیه

        try:
            # Check if already following
            try:
                user_info = self.client.user_info(user_id)
                username = user_info.username
            except Exception as e:
                logger.error(f"Error getting user info: {str(e)}")
                username = "unknown"

            # Check if we already have a record for this user
            existing_record = self.db.query(UserFollowing).filter(
                UserFollowing.user_id == user_id
            ).first()

            if existing_record and existing_record.is_following:
                logger.info(f"Already following user {username} ({user_id})")
                return False

            # ثبت درخواست در مدیریت کننده محدودیت
            rate_limit_handler.log_request("follow")

            # Follow the user
            result = self.client.user_follow(user_id)

            if result:
                # ثبت موفقیت در مدیریت کننده محدودیت
                rate_limit_handler.clear_rate_limit()

                # ریست شمارنده خطا
                self.error_count = 0

                # Record the activity
                activity = BotActivity(
                    activity_type="follow",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="success"
                )
                self.db.add(activity)

                # Update or create user following record
                if existing_record:
                    existing_record.is_following = True
                    existing_record.followed_at = datetime.now(timezone.utc)
                    existing_record.unfollowed_at = None
                else:
                    following = UserFollowing(
                        user_id=user_id,
                        username=username,
                        is_following=True
                    )
                    self.db.add(following)

                # Update daily stats
                today = datetime.now(timezone.utc).date()
                stats = self.db.query(DailyStats).filter(
                    DailyStats.date >= today
                ).first()

                if stats:
                    stats.follows_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        follows_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully followed user {username} ({user_id})")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="follow",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="failed",
                    details="Follow operation returned False"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(f"Failed to follow user {username} ({user_id})")
                return False

        except (PleaseWaitFewMinutes, RateLimitError) as e:
            # محدودیت نرخ درخواست
            error_message = str(e)
            logger.warning(
                f"Rate limit hit during follow operation: {error_message}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="follow",
                target_user_id=user_id,
                target_user_username="unknown",
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
                logger.info(
                    f"Will retry following after {wait_seconds} seconds")
                # حداکثر 5 دقیقه صبر می‌کنیم
                time.sleep(min(wait_seconds, 300))
                return self.follow_user(user_id, retry_count + 1)

            return False

        except (UserNotFound, LoginRequired) as e:
            # خطای کاربر یافت نشد یا نیاز به لاگین
            logger.error(f"User not found or login required: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="follow",
                target_user_id=user_id,
                target_user_username="unknown",
                status="failed",
                details=str(e)
            )
            self.db.add(activity)
            self.db.commit()

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

        except ClientError as e:
            # سایر خطاهای کلاینت
            logger.error(f"Client error following user {user_id}: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="follow",
                target_user_id=user_id,
                target_user_username="unknown",
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
            logger.error(f"Error following user {user_id}: {str(e)}")

            try:
                # Record the error
                activity = BotActivity(
                    activity_type="follow",
                    target_user_id=user_id,
                    target_user_username="unknown",
                    status="failed",
                    details=f"Unexpected error: {str(e)}"
                )
                self.db.add(activity)
                self.db.commit()
            except Exception as db_error:
                logger.error(
                    f"Error recording follow failure: {str(db_error)}")

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

    def follow_hashtag_users(self, hashtag, max_users=5):
        """Follow users who posted with the given hashtag"""
        if not self.can_perform_action():
            logger.info(f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
            return 0

        try:
            # Get medias by hashtag with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("generic")

                # برای پیدا کردن تعداد بیشتری پست، درخواست می‌کنیم
                medias = self.client.hashtag_medias_recent(
                    hashtag, max_users * 3)

                if not medias:
                    logger.warning(f"No medias found for hashtag #{hashtag}")
                    return 0
            except Exception as e:
                logger.error(
                    f"Error following hashtag users for {hashtag}: {str(e)}")
                return 0

            followed_count = 0
            random.shuffle(medias)  # Randomize to make it more human-like

            # افزودن تأخیر کوتاه قبل از شروع فالو‌ها
            time.sleep(random.uniform(3, 7))

            for media in medias[:max_users * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
                    break

                # اگر به تعداد کافی فالو کردیم، خارج شویم
                if followed_count >= max_users:
                    break

                user_id = media.user.pk

                # افزودن تأخیر تصادفی بین فالو‌ها
                if followed_count > 0:
                    delay = random.uniform(30, 60)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next hashtag follow")
                    time.sleep(delay)

                # Follow the user
                if self.follow_user(user_id):
                    followed_count += 1

            return followed_count

        except Exception as e:
            logger.error(
                f"Error following hashtag users for {hashtag}: {str(e)}")
            return 0

    def follow_user_followers(self, target_username, max_users=5):
        """Follow followers of a specific user"""
        if not self.can_perform_action():
            logger.info(f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
            return 0

        try:
            # Get user ID from username
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                target_user_id = self.client.user_id_from_username(
                    target_username)
            except Exception as e:
                logger.error(
                    f"Error getting user ID for {target_username}: {str(e)}")
                return 0

            # Get followers
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالوئرها برای کاهش فشار بر API
                followers = self.client.user_followers(
                    target_user_id, amount=max_users * 2)

                if not followers:
                    logger.warning(f"No followers found for {target_username}")
                    return 0
            except Exception as e:
                logger.error(
                    f"Error getting followers of {target_username}: {str(e)}")
                return 0

            followed_count = 0
            # Convert to list and shuffle to make it more human-like
            follower_ids = list(followers.keys())
            random.shuffle(follower_ids)

            # افزودن تأخیر کوتاه قبل از شروع فالو‌ها
            time.sleep(random.uniform(3, 7))

            for user_id in follower_ids[:max_users * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
                    break

                # اگر به تعداد کافی فالو کردیم، خارج شویم
                if followed_count >= max_users:
                    break

                # افزودن تأخیر تصادفی بین فالو‌ها
                if followed_count > 0:
                    delay = random.uniform(40, 70)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next user follower follow")
                    time.sleep(delay)

                # Follow the user
                if self.follow_user(user_id):
                    followed_count += 1

            return followed_count

        except Exception as e:
            logger.error(
                f"Error following followers of {target_username}: {str(e)}")
            return 0

    def follow_my_followers(self, max_users=10):
        """Follow users who follow me but I'm not following back"""
        if not self.can_perform_action():
            logger.info(f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
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
                my_followers = self.client.user_followers(user_id, amount=100)

                if not my_followers:
                    logger.warning("No followers found")
                    return 0
            except Exception as e:
                logger.error(f"Error getting my followers: {str(e)}")
                return 0

            # Get users I'm following
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالویینگ‌ها برای کاهش فشار بر API
                my_following = self.client.user_following(user_id, amount=100)
            except Exception as e:
                logger.error(f"Error getting my following: {str(e)}")
                return 0

            # Find users who follow me but I don't follow back
            not_following_back = set(
                my_followers.keys()) - set(my_following.keys())

            followed_count = 0
            # Convert to list and shuffle
            not_following_back_list = list(not_following_back)
            random.shuffle(not_following_back_list)

            # افزودن تأخیر کوتاه قبل از شروع فالو‌ها
            time.sleep(random.uniform(3, 7))

            for user_id in not_following_back_list[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily follow limit reached during follow back operation: {DAILY_FOLLOW_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین فالو‌ها
                if followed_count > 0:
                    delay = random.uniform(30, 60)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next follow back")
                    time.sleep(delay)

                # Follow the user
                if self.follow_user(user_id):
                    followed_count += 1

            return followed_count

        except Exception as e:
            logger.error(f"Error following my followers: {str(e)}")
            return 0

    def follow_back_new_followers(self, max_users=10):
        """Follow back users who recently followed us but we don't follow them back"""
        if not self.can_perform_action():
            logger.info(f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
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
                my_followers = self.client.user_followers(user_id, amount=100)
                follower_ids = set(my_followers.keys())

                if not my_followers:
                    logger.warning("No followers found")
                    return 0
            except Exception as e:
                logger.error(f"Error getting my followers: {str(e)}")
                return 0

            # Get users I'm following
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالویینگ‌ها برای کاهش فشار بر API
                my_following = self.client.user_following(user_id, amount=100)
                following_ids = set(my_following.keys())
            except Exception as e:
                logger.error(f"Error getting my following: {str(e)}")
                return 0

            # Find users who follow me but I don't follow back
            not_following_back = follower_ids - following_ids

            # Find recent followers from database (users who followed me in the last day)
            today = datetime.now(timezone.utc).date()
            yesterday = today - timedelta(days=1)

            # Get recent follow activities where I was the target (someone followed me)
            try:
                # This requires tracking incoming follows separately in the database
                # For now, we'll just use all users who follow us but we don't follow back
                recent_followers = not_following_back
            except Exception as e:
                logger.error(f"Error querying recent followers: {str(e)}")
                recent_followers = not_following_back

            followed_count = 0
            # Convert to list and shuffle
            recent_follower_list = list(recent_followers)
            random.shuffle(recent_follower_list)

            # افزودن تأخیر کوتاه قبل از شروع فالو‌ها
            time.sleep(random.uniform(3, 7))

            for follower_id in recent_follower_list[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily follow limit reached during follow back operation: {DAILY_FOLLOW_LIMIT}")
                    break

                # Get follower username for logging
                try:
                    follower_info = my_followers.get(follower_id)
                    username = follower_info.username if follower_info else "unknown"
                except:
                    username = "unknown"

                logger.info(
                    f"Following back user {username} who recently followed me")

                # افزودن تأخیر تصادفی بین فالو‌ها
                if followed_count > 0:
                    delay = random.uniform(30, 60)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next follow back")
                    time.sleep(delay)

                # Follow the user
                if self.follow_user(follower_id):
                    followed_count += 1
                    logger.info(f"Successfully followed back {username}")

            logger.info(f"Followed back {followed_count} new followers")
            return followed_count

        except Exception as e:
            logger.error(f"Error in follow back operation: {str(e)}")
            return 0
