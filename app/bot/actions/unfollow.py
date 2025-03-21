import random
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import UserNotFound, ClientError, PleaseWaitFewMinutes, LoginRequired, RateLimitError

from app.models.database import BotActivity, UserFollowing, DailyStats
from app.config import DAILY_UNFOLLOW_LIMIT
from app.logger import setup_logger
from app.bot.rate_limit import rate_limit_handler

# Configure logging
logger = setup_logger("unfollow_action")


class UnfollowAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db
        self.error_count = 0
        self.retry_delay = 30  # تاخیر اولیه برای تلاش مجدد (ثانیه)

    def get_daily_unfollow_count(self):
        """Get the number of unfollows for today"""
        try:
            today = datetime.now(timezone.utc).date()
            stats = self.db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if stats:
                return stats.unfollows_count
            return 0
        except Exception as e:
            logger.error(f"Error getting daily unfollow count: {str(e)}")
            # در صورت خطا، مقدار محافظه‌کارانه برگردانیم
            return DAILY_UNFOLLOW_LIMIT - 2

    def can_perform_action(self):
        """Check if we can perform an unfollow action today"""
        unfollows_count = self.get_daily_unfollow_count()
        return unfollows_count < DAILY_UNFOLLOW_LIMIT

    def unfollow_user(self, user_id, retry_count=0):
        """Unfollow a specific user by user_id with improved error handling"""
        # بررسی محدودیت نرخ درخواست
        can_proceed, wait_time = rate_limit_handler.can_proceed("unfollow")
        if not can_proceed:
            logger.info(
                f"Rate limit check suggests waiting {wait_time:.1f} seconds before unfollowing")
            if wait_time > 0:
                time.sleep(min(wait_time, 60))  # صبر کنیم، حداکثر 60 ثانیه

        try:
            # Check if we're following this user
            try:
                user_info = self.client.user_info(user_id)
                username = user_info.username
            except Exception as e:
                logger.error(f"Error getting user info: {str(e)}")
                username = "unknown"

            # Check if we have a record for this user
            existing_record = self.db.query(UserFollowing).filter(
                UserFollowing.user_id == user_id
            ).first()

            if existing_record and not existing_record.is_following:
                logger.info(f"Already unfollowed user {username} ({user_id})")
                return False

            # ثبت درخواست در مدیریت کننده محدودیت
            rate_limit_handler.log_request("unfollow")

            # Unfollow the user
            result = self.client.user_unfollow(user_id)

            if result:
                # ثبت موفقیت در مدیریت کننده محدودیت
                rate_limit_handler.clear_rate_limit()

                # ریست شمارنده خطا
                self.error_count = 0

                # Record the activity
                activity = BotActivity(
                    activity_type="unfollow",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="success"
                )
                self.db.add(activity)

                # Update or create user following record
                if existing_record:
                    existing_record.is_following = False
                    existing_record.unfollowed_at = datetime.now(timezone.utc)
                else:
                    following = UserFollowing(
                        user_id=user_id,
                        username=username,
                        is_following=False,
                        unfollowed_at=datetime.now(timezone.utc)
                    )
                    self.db.add(following)

                # Update daily stats
                today = datetime.now(timezone.utc).date()
                stats = self.db.query(DailyStats).filter(
                    DailyStats.date >= today
                ).first()

                if stats:
                    stats.unfollows_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        unfollows_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully unfollowed user {username} ({user_id})")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="unfollow",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="failed",
                    details="Unfollow operation returned False"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(
                    f"Failed to unfollow user {username} ({user_id})")
                return False

        except (PleaseWaitFewMinutes, RateLimitError) as e:
            # محدودیت نرخ درخواست
            error_message = str(e)
            logger.warning(
                f"Rate limit hit during unfollow operation: {error_message}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="unfollow",
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
                    f"Will retry unfollowing after {wait_seconds} seconds")
                # حداکثر 5 دقیقه صبر می‌کنیم
                time.sleep(min(wait_seconds, 300))
                return self.unfollow_user(user_id, retry_count + 1)

            return False

        except (UserNotFound, LoginRequired) as e:
            # خطای کاربر یافت نشد یا نیاز به لاگین
            logger.error(f"User not found or login required: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="unfollow",
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
            logger.error(f"Client error unfollowing user {user_id}: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="unfollow",
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
            logger.error(f"Error unfollowing user {user_id}: {str(e)}")

            try:
                # Record the error
                activity = BotActivity(
                    activity_type="unfollow",
                    target_user_id=user_id,
                    target_user_username="unknown",
                    status="failed",
                    details=f"Unexpected error: {str(e)}"
                )
                self.db.add(activity)
                self.db.commit()
            except Exception as db_error:
                logger.error(
                    f"Error recording unfollow failure: {str(db_error)}")

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

    def unfollow_non_followers(self, max_users=10):
        """Unfollow users who don't follow us back"""
        if not self.can_perform_action():
            logger.info(
                f"Daily unfollow limit reached: {DAILY_UNFOLLOW_LIMIT}")
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
                my_followers = self.client.user_followers(user_id, amount=100)
            except Exception as e:
                logger.error(f"Error getting my followers: {str(e)}")
                return 0

            # Get users I'm following with error handling
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالویینگ‌ها برای کاهش فشار بر API
                my_following = self.client.user_following(user_id, amount=100)

                if not my_following:
                    logger.warning("No users I'm following found")
                    return 0
            except Exception as e:
                logger.error(f"Error getting my following: {str(e)}")
                return 0

            # Find users I follow but they don't follow back
            not_following_me_back = set(
                my_following.keys()) - set(my_followers.keys())

            unfollowed_count = 0
            # Convert to list and shuffle
            not_following_me_back_list = list(not_following_me_back)
            random.shuffle(not_following_me_back_list)

            # افزودن تأخیر کوتاه قبل از شروع آنفالو‌ها
            time.sleep(random.uniform(3, 7))

            for user_id in not_following_me_back_list[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily unfollow limit reached during operation: {DAILY_UNFOLLOW_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین آنفالو‌ها
                if unfollowed_count > 0:
                    delay = random.uniform(40, 70)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next non-follower unfollow")
                    time.sleep(delay)

                # Unfollow the user
                if self.unfollow_user(user_id):
                    unfollowed_count += 1

            return unfollowed_count

        except Exception as e:
            logger.error(f"Error unfollowing non-followers: {str(e)}")
            return 0

    def unfollow_old_followings(self, days_threshold=7, max_users=10):
        """Unfollow users we've been following for more than X days who didn't follow back"""
        if not self.can_perform_action():
            logger.info(
                f"Daily unfollow limit reached: {DAILY_UNFOLLOW_LIMIT}")
            return 0

        try:
            # Calculate the threshold date
            threshold_date = datetime.now(
                timezone.utc) - timedelta(days=days_threshold)

            # Get my followers for checking who doesn't follow back
            try:
                user_id = self.client.user_id

                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالوئرها برای کاهش فشار بر API
                my_followers = self.client.user_followers(user_id, amount=100)
                follower_ids = set(my_followers.keys())
            except Exception as e:
                logger.error(
                    f"Error getting followers for unfollow old: {str(e)}")
                # ادامه دهیم با فرض اینکه هیچکس ما را فالو نمی‌کند
                follower_ids = set()

            # Find users we've been following for more than X days who didn't follow back
            try:
                old_followings = self.db.query(UserFollowing).filter(
                    UserFollowing.is_following == True,
                    UserFollowing.followed_at <= threshold_date,
                    UserFollowing.followed_back == False
                ).limit(max_users * 2).all()

                if not old_followings:
                    logger.info(
                        f"No old followings found older than {days_threshold} days")
                    return 0
            except Exception as e:
                logger.error(f"Error querying old followings: {str(e)}")
                return 0

            unfollowed_count = 0
            # Shuffle the results to make it more human-like
            random.shuffle(old_followings)

            # افزودن تأخیر کوتاه قبل از شروع آنفالو‌ها
            time.sleep(random.uniform(3, 7))

            for following in old_followings[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily unfollow limit reached during old following operation: {DAILY_UNFOLLOW_LIMIT}")
                    break

                # Check if they actually follow us now (might have changed since our last check)
                is_follower = following.user_id in follower_ids

                if is_follower:
                    # Update record if they now follow us
                    following.followed_back = True
                    self.db.commit()
                    logger.info(
                        f"User {following.username} now follows us back, not unfollowing")
                    continue

                # افزودن تأخیر تصادفی بین آنفالو‌ها
                if unfollowed_count > 0:
                    delay = random.uniform(40, 70)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next old following unfollow")
                    time.sleep(delay)

                # Unfollow the user
                if self.unfollow_user(following.user_id):
                    unfollowed_count += 1

            return unfollowed_count

        except Exception as e:
            logger.error(f"Error unfollowing old followings: {str(e)}")
            return 0

    def unfollow_users_who_unfollowed_me(self, max_users=10):
        """Unfollow users who used to follow us but unfollowed"""
        if not self.can_perform_action():
            logger.info(
                f"Daily unfollow limit reached: {DAILY_UNFOLLOW_LIMIT}")
            return 0

        try:
            # Get my user ID
            try:
                user_id = self.client.user_id

                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                # محدود کردن تعداد فالوئرها برای کاهش فشار بر API
                my_followers = self.client.user_followers(user_id, amount=100)
                follower_ids = set(my_followers.keys())
            except Exception as e:
                logger.error(f"Error getting current followers: {str(e)}")
                return 0

            # Find users who had followed back but might have unfollowed us
            try:
                potential_unfollowers = self.db.query(UserFollowing).filter(
                    UserFollowing.is_following == True,
                    UserFollowing.followed_back == True
                ).limit(max_users * 3).all()

                if not potential_unfollowers:
                    logger.info("No potential unfollowers found")
                    return 0
            except Exception as e:
                logger.error(f"Error querying potential unfollowers: {str(e)}")
                return 0

            unfollowed_count = 0
            # Shuffle the results
            random.shuffle(potential_unfollowers)

            # افزودن تأخیر کوتاه قبل از شروع آنفالو‌ها
            time.sleep(random.uniform(3, 7))

            for following in potential_unfollowers[:max_users * 2]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily unfollow limit reached during unfollowers operation: {DAILY_UNFOLLOW_LIMIT}")
                    break

                # اگر به تعداد کافی آنفالو کردیم، خارج شویم
                if unfollowed_count >= max_users:
                    break

                # Check if they still follow us
                still_follows = following.user_id in follower_ids

                if not still_follows:
                    # They unfollowed us, so unfollow them back

                    # افزودن تأخیر تصادفی بین آنفالو‌ها
                    if unfollowed_count > 0:
                        delay = random.uniform(40, 70)
                        logger.info(
                            f"Waiting {delay:.1f} seconds before next unfollower unfollow")
                        time.sleep(delay)

                    if self.unfollow_user(following.user_id):
                        unfollowed_count += 1
                        # ثبت تغییر در پایگاه داده
                        following.followed_back = False
                        self.db.commit()

            return unfollowed_count

        except Exception as e:
            logger.error(
                f"Error unfollowing users who unfollowed me: {str(e)}")
            return 0
