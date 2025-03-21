import logging
import random
import threading
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR

from app.models.database import check_db_health
from app.bot.client import InstagramClient
from app.bot.actions import ActionManager
from app.bot.monitor import bot_monitor
from app.bot.utils import (
    random_delay,
    should_rest,
    take_rest,
    choose_random_activity,
    update_follower_counts
)
from app.config import (
    RANDOM_ACTIVITY_MODE,
    MIN_DELAY_BETWEEN_ACTIONS,
    MAX_DELAY_BETWEEN_ACTIONS
)
from app.logger import setup_logger

# Setup logger
logger = setup_logger("scheduler")


class BotScheduler:
    def __init__(self, db: Session):
        self.db = db
        self.client = InstagramClient(db)
        self.actions = None
        self.scheduler = None  # Will be initialized in start()
        self.running = False
        self.lock = threading.Lock()  # Lock to prevent concurrent actions
        # اضافه کردن متغیر برای نگهداری وضعیت استراحت
        self.is_resting = False
        self.rest_start_time = None
        self.rest_duration = 0
        # اضافه کردن متغیر برای زمان گرفتن قفل
        self.lock_acquired_time = None
        # اضافه کردن شمارنده تلاش‌ها
        self.restart_attempts = 0
        # تاخیر بین درخواست‌ها
        self.min_delay = MIN_DELAY_BETWEEN_ACTIONS
        self.max_delay = MAX_DELAY_BETWEEN_ACTIONS

    def _handle_db_error(self, operation, e):
        """Handle database errors gracefully"""
        logger.error(f"Database error during {operation}: {str(e)}")
        # اگر خطای connection است، تلاش کنید دوباره ترنزکشن را برگردانید
        try:
            self.db.rollback()
            logger.info("Rolled back database transaction")
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {str(rollback_error)}")

    def initialize(self):
        """Initialize the bot by loading session or logging in"""
        try:
            # ابتدا سعی در بارگذاری نشست موجود
            if self.client.load_session():
                logger.info("Successfully loaded existing session")
                self.actions = ActionManager(self.client.get_client(), self.db)
                return True

            # اگر نشست موجود نبود، تلاش برای ورود جدید
            if self.client.login():
                self.actions = ActionManager(self.client.get_client(), self.db)
                logger.info("Bot initialized successfully with new login")
                return True
            else:
                logger.error("Failed to initialize bot - login failed")
                return False
        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("initialize", e)
            else:
                logger.error(f"Error initializing bot: {str(e)}")
            return False

    def job_error_listener(self, event):
        """Handler for job execution errors"""
        logger.error(f"Job execution error: {event.exception}")
        logger.error(f"Traceback: {event.traceback}")

        # ثبت خطا در مانیتور
        if 'bot_monitor' in globals():
            bot_monitor.record_error(f"Job error: {str(event.exception)}")

    def start(self):
        """Start the bot scheduler"""
        try:
            if not self.initialize():
                return False

            # ایجاد یک scheduler جدید
            if self.scheduler and self.scheduler.running:
                logger.warning(
                    "Scheduler is already running. Stopping it first...")
                try:
                    self.scheduler.shutdown(wait=False)
                except Exception as shutdown_error:
                    logger.error(
                        f"Error shutting down existing scheduler: {str(shutdown_error)}")

            # ایجاد scheduler جدید
            self.scheduler = BackgroundScheduler()

            # اضافه کردن listener برای خطاهای اجرای job
            self.scheduler.add_listener(
                self.job_error_listener, EVENT_JOB_ERROR)

            # Schedule the main activity task
            self.scheduler.add_job(
                self.perform_activity,
                # فاصله بین فعالیت‌ها 15-25 دقیقه (تصادفی برای طبیعی‌تر بودن)
                trigger=IntervalTrigger(minutes=random.randint(15, 25)),
                id='activity_job',
                replace_existing=True,
                max_instances=1  # اطمینان از حداکثر یک نمونه در حال اجرا
            )

            # Schedule daily follower count update
            self.scheduler.add_job(
                self.update_follower_stats,
                trigger=IntervalTrigger(hours=6),  # Update 4 times per day
                id='follower_stats_job',
                replace_existing=True
            )

            # اضافه کردن جاب مانیتورینگ برای بررسی وضعیت قفل
            self.scheduler.add_job(
                self.monitor_lock_status,
                trigger=IntervalTrigger(minutes=5),  # بررسی هر 5 دقیقه
                id='lock_monitor_job',
                replace_existing=True
            )

            # اضافه کردن بررسی سلامت دیتابیس
            self.scheduler.add_job(
                check_db_health,
                trigger=IntervalTrigger(minutes=10),  # بررسی هر 10 دقیقه
                id='db_health_check_job',
                replace_existing=True
            )

            # ریست کردن وضعیت استراحت
            self.is_resting = False
            self.rest_start_time = None
            self.rest_duration = 0
            self.lock_acquired_time = None
            self.restart_attempts = 0

            self.scheduler.start()
            self.running = True
            logger.info("Bot scheduler started")

            # اجرای یک فعالیت اولیه بلافاصله پس از شروع با تاخیر کم
            self.scheduler.add_job(
                self.perform_activity,
                trigger='date',
                run_date=datetime.now() + timedelta(seconds=30),
                id='initial_job'
            )
            logger.info("Scheduled initial activity for 30 seconds from now")

            return True
        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("start", e)
            else:
                logger.error(f"Error starting scheduler: {str(e)}")
            return False

    def stop(self):
        """Stop the bot scheduler"""
        try:
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            self.running = False
            # ریست وضعیت استراحت
            self.is_resting = False
            self.rest_start_time = None
            self.rest_duration = 0
            logger.info("Bot scheduler stopped")
            return True
        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("stop", e)
            else:
                logger.error(f"Error stopping scheduler: {str(e)}")
            return False

    def restart(self):
        """Restart the bot scheduler properly"""
        try:
            logger.info("Attempting to restart the bot scheduler...")
            self.restart_attempts += 1

            # اگر تعداد تلاش‌ها بیش از حد است، یک تاخیر اضافه کنیم
            if self.restart_attempts > 3:
                delay = min(30 * self.restart_attempts, 300)  # حداکثر 5 دقیقه
                logger.warning(
                    f"Multiple restart attempts detected ({self.restart_attempts}). Waiting {delay} seconds before trying again...")
                time.sleep(delay)

            # اول به طور کامل متوقف می‌کنیم
            if self.running:
                logger.info("Stopping current scheduler...")
                self.stop()
                # کمی صبر می‌کنیم تا به طور کامل بسته شود
                time.sleep(5)

            # راه‌اندازی مجدد
            logger.info("Starting new scheduler...")
            result = self.start()

            if result:
                self.restart_attempts = 0  # ریست کردن شمارنده در صورت موفقیت
                logger.info("Bot successfully restarted")
            else:
                logger.error("Failed to restart bot")

            return result

        except Exception as e:
            logger.error(f"Error during bot restart: {str(e)}")
            return False

    def monitor_lock_status(self):
        """Monitor lock status and release if necessary"""
        try:
            # بررسی اگر استراحت در حال انجام است و زمان آن گذشته
            if self.is_resting and self.rest_start_time and self.rest_duration > 0:
                elapsed_time = (datetime.now() -
                                self.rest_start_time).total_seconds()
                if elapsed_time >= self.rest_duration:
                    logger.warning(
                        f"Rest period of {self.rest_duration} seconds has expired but lock wasn't released. Forcibly releasing lock.")
                    self.is_resting = False
                    self.rest_start_time = None
                    self.rest_duration = 0
                    if self.lock.locked():
                        try:
                            self.lock.release()
                            logger.info(
                                "Lock forcibly released after rest period expired")
                        except Exception as e:
                            logger.error(
                                f"Error releasing lock after rest: {str(e)}")

            # بررسی اگر قفل گرفته شده و بیش از حد معقول گذشته (احتمالاً خطایی رخ داده)
            elif self.lock.locked() and self.lock_acquired_time:
                elapsed_time = (datetime.now() -
                                self.lock_acquired_time).total_seconds()
                if elapsed_time > 1800:  # 30 دقیقه
                    logger.warning(
                        f"Lock has been held for {elapsed_time/60:.1f} minutes without release. Forcibly releasing.")
                    try:
                        self.lock.release()
                        logger.info("Lock forcibly released")
                        self.lock_acquired_time = None
                    except Exception as e:
                        logger.error(f"Error releasing lock: {str(e)}")

        except Exception as e:
            logger.error(f"Error in lock monitor: {str(e)}")

    def perform_activity(self):
        """Perform a bot activity based on schedule and limits"""
        # بررسی وضعیت استراحت قبل از تلاش برای گرفتن قفل
        if self.is_resting:
            # استفاده از datetime.now
            current_time = datetime.now(timezone.utc)
            elapsed_time = (
                current_time - self.rest_start_time).total_seconds()
            if elapsed_time < self.rest_duration:
                remaining = self.rest_duration - elapsed_time
                logger.info(
                    f"Still in rest period. {int(remaining)} seconds remaining until next activity. Started at {self.rest_start_time.strftime('%H:%M:%S')}."
                )
                # اضافه کنیم که چه زمانی فعالیت بعدی شروع می‌شود
                next_activity_time = self.rest_start_time + \
                    timedelta(seconds=self.rest_duration)
                logger.info(
                    f"Next activity scheduled at approximately: {next_activity_time.strftime('%H:%M:%S')}"
                )
                return
            else:
                # زمان استراحت تمام شده
                self.is_resting = False
                self.rest_start_time = None
                self.rest_duration = 0
                logger.info(
                    f"Rest period completed at {datetime.now(timezone.utc).strftime('%H:%M:%S')}. Resuming activities."
                )

                # اطمینان از آزاد بودن قفل
                if self.lock.locked():
                    try:
                        self.lock.release()
                        logger.info(
                            "Lock was still held after rest, released it"
                        )
                    except Exception as e:
                        logger.error(
                            f"Error releasing lock after rest: {str(e)}")

        # Use lock to prevent concurrent actions with timeout
        try:
            lock_acquired = self.lock.acquire(blocking=True, timeout=10)
            if not lock_acquired:
                logger.warning(
                    "Could not acquire lock after 10 seconds, another activity might be in progress")
                return

            # ذخیره زمان گرفتن قفل
            self.lock_acquired_time = datetime.now(timezone.utc)
            logger.info("Lock acquired, preparing to perform activity")

            # اضافه کردن تاخیر تصادفی قبل از شروع
            wait_time = random.randint(2, 8)
            logger.info(
                f"Waiting {wait_time} seconds before starting activity...")
            time.sleep(wait_time)

            # Check if we should take a rest
            if should_rest():
                logger.info("Decision made to take a rest")

                # تنظیم وضعیت استراحت
                self.is_resting = True
                self.rest_start_time = datetime.now(timezone.utc)

                # کم کردن زمان استراحت برای تست (بین 1 تا 5 دقیقه)
                rest_minutes = random.uniform(3, 8)
                self.rest_duration = rest_minutes * 60

                logger.info(
                    f"Setting rest period for {rest_minutes:.2f} minutes ({self.rest_duration} seconds)"
                )

                # اجرای استراحت
                take_rest()

                # آزاد کردن قفل قبل از بازگشت
                if self.lock.locked():
                    self.lock.release()
                    self.lock_acquired_time = None
                    logger.info("Lock released before rest")
                return

            # Choose a random activity if in random mode, otherwise cycle through activities
            if RANDOM_ACTIVITY_MODE:
                activity = choose_random_activity()
            else:
                # In a real implementation, you might want a more sophisticated approach
                # For simplicity, we'll just use random here as well
                activity = choose_random_activity()

            logger.info(f"Performing activity: {activity}")
            # اضافه کردن تخمین زمان پایان فعالیت
            estimated_completion_time = datetime.now(
                timezone.utc) + timedelta(minutes=1)  # تخمین حدودی
            logger.info(
                f"Estimated completion time: {estimated_completion_time.strftime('%H:%M:%S')}"
            )

            # Perform the selected activity
            if activity == "follow":
                self.perform_follow_activity()
            elif activity == "unfollow":
                self.perform_unfollow_activity()
            elif activity == "like":
                self.perform_like_activity()
            elif activity == "comment":
                self.perform_comment_activity()
            elif activity == "direct":
                self.perform_direct_activity()
            elif activity == "story_reaction":
                self.perform_story_reaction_activity()

            # محاسبه و لاگ زمان فعالیت بعدی - زمان تصادفی برای طبیعی‌تر بودن
            next_minutes = random.randint(15, 25)
            next_activity_time = datetime.now(
                timezone.utc) + timedelta(minutes=next_minutes)
            logger.info(
                f"Next scheduled activity will start at approximately: {next_activity_time.strftime('%H:%M:%S')} ({next_minutes} minutes from now)"
            )

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("perform_activity", e)
            else:
                logger.error(f"Error performing activity: {str(e)}")

                # افزودن ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "loginrequired", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
                        bot_monitor.record_error(str(e))
                    else:
                        logger.warning(
                            "Bot monitor not available to record error")

                # اگر خطا مربوط به نشست بود، سعی در ورود مجدد
                if "login_required" in str(e).lower() or "loginrequired" in str(e).lower():
                    logger.info(
                        "Session expired. Attempting to login again...")
                    self.client.login()
        finally:
            # آزاد کردن قفل در انتها با بررسی امن
            try:
                if self.lock.locked():
                    self.lock.release()
                    self.lock_acquired_time = None
                    logger.info("Lock released after activity")
            except Exception as e:
                logger.error(f"Error releasing lock: {str(e)}")

    def perform_follow_activity(self):
        """Perform follow-related activities"""
        try:
            # Choose a random follow action
            action = random.choice([
                "follow_hashtag_users",
                "follow_user_followers",
                "follow_my_followers"
            ])

            if action == "follow_hashtag_users":
                # Choose a random hashtag from our topics
                from app.data.topics import HASHTAGS
                if HASHTAGS:
                    hashtag = random.choice(HASHTAGS)
                    count = self.actions.follow.follow_hashtag_users(
                        hashtag, max_users=2)
                    logger.info(
                        f"Followed {count} users from hashtag #{hashtag}")

            elif action == "follow_user_followers":
                # Choose a user from our topics
                from app.data.topics import TARGET_USERS
                if TARGET_USERS:
                    username = random.choice(TARGET_USERS)
                    count = self.actions.follow.follow_user_followers(
                        username, max_users=2)
                    logger.info(
                        f"Followed {count} followers of user {username}")

            elif action == "follow_my_followers":
                count = self.actions.follow.follow_my_followers(
                    max_users=2)
                logger.info(
                    f"Followed {count} of my followers that I wasn't following back")

            # Add a delay before the next action
            delay = random_delay(self.min_delay, self.max_delay)
            logger.info(
                f"Added {delay:.1f} seconds delay after follow activity")

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("follow_activity", e)
            else:
                logger.error(f"Error in follow activity: {str(e)}")
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    bot_monitor.record_error(
                        f"Follow activity error: {str(e)}")

    def perform_unfollow_activity(self):
        """Perform unfollow-related activities"""
        try:
            # Choose a random unfollow action
            action = random.choice([
                "unfollow_non_followers",
                "unfollow_old_followings",
                "unfollow_users_who_unfollowed_me"
            ])

            if action == "unfollow_non_followers":
                count = self.actions.unfollow.unfollow_non_followers(
                    max_users=2)
                logger.info(
                    f"Unfollowed {count} users who don't follow me back")

            elif action == "unfollow_old_followings":
                # Random days threshold between 7-14 days
                days = random.randint(7, 14)
                count = self.actions.unfollow.unfollow_old_followings(
                    days_threshold=days, max_users=2)
                logger.info(
                    f"Unfollowed {count} users who didn't follow back after {days} days")

            elif action == "unfollow_users_who_unfollowed_me":
                count = self.actions.unfollow.unfollow_users_who_unfollowed_me(
                    max_users=2)
                logger.info(f"Unfollowed {count} users who unfollowed me")

            # Add a delay before the next action
            delay = random_delay(self.min_delay, self.max_delay)
            logger.info(
                f"Added {delay:.1f} seconds delay after unfollow activity")

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("unfollow_activity", e)
            else:
                logger.error(f"Error in unfollow activity: {str(e)}")
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    bot_monitor.record_error(
                        f"Unfollow activity error: {str(e)}")

    def perform_like_activity(self):
        """Perform like-related activities"""
        try:
            # Choose a random like action
            action = random.choice([
                "like_hashtag_medias",
                "like_user_media",
                "like_followers_media",
                "like_feed_medias"
            ])

            if action == "like_hashtag_medias":
                # Choose a random hashtag from our topics
                from app.data.topics import HASHTAGS
                if HASHTAGS:
                    hashtag = random.choice(HASHTAGS)
                    count = self.actions.like.like_hashtag_medias(
                        hashtag, max_likes=3)
                    logger.info(f"Liked {count} posts from hashtag #{hashtag}")

            elif action == "like_user_media":
                # Choose a user from our topics
                from app.data.topics import TARGET_USERS
                if TARGET_USERS:
                    username = random.choice(TARGET_USERS)
                    user_id = self.client.get_client().user_id_from_username(username)
                    count = self.actions.like.like_user_media(
                        user_id, max_likes=2)
                    logger.info(f"Liked {count} posts from user {username}")

            elif action == "like_followers_media":
                count = self.actions.like.like_followers_media(
                    max_users=1, posts_per_user=2)
                logger.info(f"Liked {count} posts from my followers")

            elif action == "like_feed_medias":
                count = self.actions.like.like_feed_medias(
                    max_likes=3)
                logger.info(f"Liked {count} posts from my feed")

            # Add a delay before the next action
            delay = random_delay(self.min_delay, self.max_delay)
            logger.info(f"Added {delay:.1f} seconds delay after like activity")

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("like_activity", e)
            else:
                logger.error(f"Error in like activity: {str(e)}")
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    bot_monitor.record_error(f"Like activity error: {str(e)}")

    def perform_comment_activity(self):
        """Perform comment-related activities"""
        try:
            # Choose a random comment action
            action = random.choice([
                "comment_on_hashtag_medias",
                "comment_on_followers_media",
                "comment_on_feed_medias"
            ])

            if action == "comment_on_hashtag_medias":
                # Choose a random hashtag from our topics
                from app.data.topics import HASHTAGS
                if HASHTAGS:
                    hashtag = random.choice(HASHTAGS)
                    count = self.actions.comment.comment_on_hashtag_medias(
                        hashtag, max_comments=1)
                    logger.info(
                        f"Commented on {count} posts from hashtag #{hashtag}")

            elif action == "comment_on_followers_media":
                count = self.actions.comment.comment_on_followers_media(
                    max_users=1)
                logger.info(f"Commented on {count} posts from my followers")

            elif action == "comment_on_feed_medias":
                count = self.actions.comment.comment_on_feed_medias(
                    max_comments=1)
                logger.info(f"Commented on {count} posts from my feed")

            # Add a delay before the next action
            delay = random_delay(self.min_delay, self.max_delay)
            logger.info(
                f"Added {delay:.1f} seconds delay after comment activity")

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("comment_activity", e)
            else:
                logger.error(f"Error in comment activity: {str(e)}")
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    bot_monitor.record_error(
                        f"Comment activity error: {str(e)}")

    def perform_direct_activity(self):
        """Perform direct message-related activities"""
        try:
            # Choose a random direct message action
            action = random.choice([
                "send_welcome_messages_to_new_followers",
                "send_engagement_messages",
                "send_inactive_follower_messages"
            ])

            if action == "send_welcome_messages_to_new_followers":
                count = self.actions.direct.send_welcome_messages_to_new_followers(
                    max_messages=1)
                logger.info(f"Sent welcome messages to {count} new followers")

            elif action == "send_engagement_messages":
                count = self.actions.direct.send_engagement_messages(
                    max_messages=1)
                logger.info(f"Sent engagement messages to {count} users")

            elif action == "send_inactive_follower_messages":
                count = self.actions.direct.send_inactive_follower_messages(
                    days_inactive=30, max_messages=1)
                logger.info(f"Sent messages to {count} inactive followers")

            # Add a delay before the next action
            delay = random_delay(self.min_delay, self.max_delay)
            logger.info(
                f"Added {delay:.1f} seconds delay after direct message activity")

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("direct_activity", e)
            else:
                logger.error(f"Error in direct message activity: {str(e)}")
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    bot_monitor.record_error(
                        f"Direct message activity error: {str(e)}")

    def perform_story_reaction_activity(self):
        """Perform story reaction-related activities"""
        try:
            # Choose a random story reaction action
            action = random.choice([
                "react_to_followers_stories",
                "react_to_following_stories"
            ])

            if action == "react_to_followers_stories":
                count = self.actions.story_reaction.react_to_followers_stories(
                    max_users=2, max_reactions_per_user=1)
                logger.info(f"Reacted to {count} stories from my followers")

            elif action == "react_to_following_stories":
                count = self.actions.story_reaction.react_to_following_stories(
                    max_users=2, max_reactions_per_user=1)
                logger.info(f"Reacted to {count} stories from users I follow")

            # Add a delay before the next action
            delay = random_delay(self.min_delay, self.max_delay)
            logger.info(
                f"Added {delay:.1f} seconds delay after story reaction activity")

        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("story_reaction_activity", e)
            else:
                logger.error(f"Error in story reaction activity: {str(e)}")
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    bot_monitor.record_error(
                        f"Story reaction activity error: {str(e)}")

    def update_follower_stats(self):
        """Update follower statistics in the database"""
        try:
            update_follower_counts(self.client.get_client(), self.db)
        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("update_follower_stats", e)
            else:
                logger.error(f"Error updating follower stats: {str(e)}")
