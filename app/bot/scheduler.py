import logging
import random
import threading
import time
import traceback
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.jobstores.memory import MemoryJobStore

from app.models.database import check_db_health, backup_database_data
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
        # شمارنده خطاها (برای استراحت طولانی‌تر)
        self.error_count = 0
        self.error_reset_time = datetime.now(timezone.utc)
        # آخرین فعالیت موفق
        self.last_successful_activity = None
        # زمان آخرین بررسی وضعیت نشست
        self.last_session_check = datetime.now(timezone.utc)
        # تعداد بررسی وضعیت نشست
        self.session_check_counter = 0

        # تنظیم دستی API در صورت لزوم
        # تعداد خطاهای متوالی قبل از راه‌اندازی مجدد اجباری
        self.max_consecutive_errors = 15
        self.consecutive_errors = 0  # شمارنده خطاهای متوالی

        # وضعیت سلامت
        self.health_status = {
            "db_connection": True,
            "instagram_login": False,
            "last_successful_activity": None,
            "errors_since_restart": 0,
            "last_error": None,
            "last_session_check": None,
            "session_check_result": None,
            "restart_count": 0
        }

        # استراتژی فعالیت‌ها - استفاده از استراتژی هوشمندتر
        self.dynamically_adjust_activity_weights()

    def dynamically_adjust_activity_weights(self):
        """تنظیم پویای وزن‌های فعالیت بر اساس شرایط"""
        # مقادیر پایه
        self.activity_weights = {
            "follow": 1,
            "unfollow": 1,
            "like": 3,
            "comment": 1,
            "direct": 1,
            "story_reaction": 2
        }

        # تنظیم بر اساس ساعت روز (به وقت ایران)
        current_hour = (datetime.now(timezone.utc).hour + 3.5) % 24

        # ساعات شلوغ (10 صبح تا 11 شب به وقت ایران)
        if 10 <= current_hour <= 23:
            # کاهش فعالیت‌های حساس در ساعات شلوغ
            self.activity_weights["follow"] *= 0.8
            self.activity_weights["unfollow"] *= 0.8
            self.activity_weights["comment"] *= 0.8
            self.activity_weights["direct"] *= 0.7

            # افزایش فعالیت‌های کم‌خطرتر
            self.activity_weights["like"] *= 1.3
            self.activity_weights["story_reaction"] *= 1.2
        else:
            # ساعات خلوت‌تر - وزن بیشتر به فعالیت‌های حساس‌تر
            self.activity_weights["follow"] *= 1.2
            self.activity_weights["unfollow"] *= 1.1
            self.activity_weights["comment"] *= 1.0
            self.activity_weights["direct"] *= 0.9

        # تنظیم بر اساس شمارنده خطا
        if self.error_count > 0:
            error_factor = min(self.error_count * 0.2, 0.8)  # حداکثر 80% کاهش

            # کاهش وزن همه فعالیت‌ها به جز لایک
            for activity in ["follow", "unfollow", "comment", "direct"]:
                self.activity_weights[activity] *= (1 - error_factor)

            # افزایش وزن فعالیت‌های کم‌خطر
            self.activity_weights["like"] *= (1 + error_factor * 0.5)
            self.activity_weights["story_reaction"] *= (1 + error_factor * 0.3)

        logger.info(f"Adjusted activity weights: {self.activity_weights}")

    def _handle_db_error(self, operation, e):
        """Handle database errors gracefully"""
        logger.error(f"Database error during {operation}: {str(e)}")
        # اگر خطای connection است، تلاش کنید دوباره ترنزکشن را برگردانید
        try:
            self.db.rollback()
            logger.info("Rolled back database transaction")
            # ثبت در وضعیت سلامت
            self.health_status["db_connection"] = False
            self.health_status["last_error"] = f"DB error: {str(e)}"
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {str(rollback_error)}")

    def initialize(self):
        """Initialize the bot by loading session or logging in with improved error handling"""
        try:
            # ثبت تلاش راه‌اندازی
            self.health_status["restart_count"] += 1

            # ابتدا سعی در بارگذاری نشست موجود
            if self.client.load_session():
                logger.info("Successfully loaded existing session")
                self.actions = ActionManager(self.client.get_client(), self.db)

                # بررسی اعتبار نشست
                if self.verify_session_health():
                    self.health_status["instagram_login"] = True
                    return True
                else:
                    logger.warning(
                        "Session loaded but verification failed, attempting to login")

            # اگر نشست موجود نبود یا معتبر نبود، تلاش برای ورود جدید
            if self.client.login():
                self.actions = ActionManager(self.client.get_client(), self.db)
                logger.info("Bot initialized successfully with new login")
                self.health_status["instagram_login"] = True
                return True
            else:
                logger.error("Failed to initialize bot - login failed")
                self.health_status["instagram_login"] = False
                return False
        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("initialize", e)
            else:
                logger.error(f"Error initializing bot: {str(e)}")
                logger.error(traceback.format_exc())

            self.health_status["instagram_login"] = False
            self.health_status["last_error"] = f"Init error: {str(e)}"
            return False

    def verify_session_health(self):
        """بررسی سلامت و اعتبار نشست اینستاگرام"""
        try:
            now = datetime.now(timezone.utc)
            self.last_session_check = now
            self.session_check_counter += 1
            self.health_status["last_session_check"] = now.isoformat()

            # بررسی وضعیت نشست با client
            result = self.client.verify_session()

            if result:
                logger.info("Session verification passed")
                self.health_status["session_check_result"] = "pass"
                return True
            else:
                logger.warning("Session verification failed")
                self.health_status["session_check_result"] = "fail"
                return False

        except Exception as e:
            logger.error(f"Error during session verification: {str(e)}")
            self.health_status["session_check_result"] = f"error: {str(e)}"
            return False

    def job_error_listener(self, event):
        """Handler for job execution errors with improved error tracking"""
        logger.error(f"Job execution error: {event.exception}")
        logger.error(f"Traceback: {event.traceback}")

        # افزایش شمارنده خطاها
        self.error_count += 1
        self.consecutive_errors += 1
        self.health_status["errors_since_restart"] += 1
        self.health_status["last_error"] = str(event.exception)

        # ریست شمارنده خطاها هر 6 ساعت
        if (datetime.now(timezone.utc) - self.error_reset_time).total_seconds() > 21600:  # 6 ساعت
            self.error_count = 1  # شروع از 1 بعد از ریست (خطای فعلی)
            self.error_reset_time = datetime.now(timezone.utc)
            logger.info("Error count reset after 6 hours")

        # اگر تعداد خطاهای متوالی از حد مجاز بیشتر شد، درخواست راه‌اندازی مجدد می‌دهیم
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.critical(
                f"Detected {self.consecutive_errors} consecutive errors - requesting forced restart")

            # ذخیره وضعیت برای بررسی‌های آینده
            try:
                error_state = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "consecutive_errors": self.consecutive_errors,
                    "last_error": str(event.exception),
                    "health_status": self.health_status
                }

                with open("/app/logs/critical_errors.json", "w") as f:
                    json.dump(error_state, f, indent=2)
            except Exception as save_error:
                logger.error(f"Could not save error state: {str(save_error)}")

            # راه‌اندازی مجدد اجباری
            self.restart()

            # ریست شمارنده خطاهای متوالی
            self.consecutive_errors = 0

        # ثبت خطا در مانیتور
        if 'bot_monitor' in globals():
            bot_monitor.record_error(f"Job error: {str(event.exception)}")

    def job_success_listener(self, event):
        """Handler for successful job execution"""
        # تنظیم زمان آخرین فعالیت موفق
        self.last_successful_activity = datetime.now(timezone.utc)
        self.health_status["last_successful_activity"] = self.last_successful_activity.isoformat(
        )

        # ریست شمارنده خطاهای متوالی
        self.consecutive_errors = 0

        # کاهش شمارنده خطاها در صورت موفقیت
        if self.error_count > 0:
            self.error_count -= 0.5  # کاهش تدریجی شمارنده خطاها
            if self.error_count < 0:
                self.error_count = 0

    def job_missed_listener(self, event):
        """Handler for missed job executions"""
        logger.warning(f"Job missed execution: {event.job_id}")

        # اگر چندین job از دست رفته باشد، ممکن است سیستم دچار مشکل شده باشد
        if event.job_id == 'activity_job':
            # فقط برای job اصلی فعالیت به شمارنده اضافه می‌کنیم
            self.consecutive_errors += 0.5  # نیم خطا برای هر job از دست رفته

    def start(self):
        """Start the bot scheduler with improved error handling"""
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

            # ایجاد scheduler جدید با تنظیمات پیشرفته‌تر
            job_stores = {
                'default': MemoryJobStore()
            }

            self.scheduler = BackgroundScheduler(
                jobstores=job_stores,
                job_defaults={
                    'coalesce': True,  # ادغام اجراهای از دست رفته
                    'max_instances': 1,  # فقط یک نمونه از هر job
                    'misfire_grace_time': 60  # اجازه 60 ثانیه تاخیر در اجرا
                }
            )

            # اضافه کردن listener برای خطاهای اجرای job
            self.scheduler.add_listener(
                self.job_error_listener, EVENT_JOB_ERROR)

            # اضافه کردن listener برای اجرای موفق job
            self.scheduler.add_listener(
                self.job_success_listener, EVENT_JOB_EXECUTED)

            # اضافه کردن listener برای جاب‌های از دست رفته
            self.scheduler.add_listener(
                self.job_missed_listener, EVENT_JOB_MISSED)

            # تنظیم فاصله زمانی تصادفی‌تر بین فعالیت‌ها (15-40 دقیقه)
            interval_minutes = random.randint(15, 40)

            # Schedule the main activity task
            self.scheduler.add_job(
                self.perform_activity,
                trigger=IntervalTrigger(minutes=interval_minutes),
                id='activity_job',
                replace_existing=True,
                max_instances=1  # اطمینان از حداکثر یک نمونه در حال اجرا
            )
            logger.info(
                f"Main activity job scheduled to run every {interval_minutes} minutes")

            # Schedule follower count update more frequently (every 4 hours)
            self.scheduler.add_job(
                self.update_follower_stats,
                trigger=IntervalTrigger(hours=4),
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

            # اضافه کردن بررسی سلامت دیتابیس به صورت مکرر
            self.scheduler.add_job(
                check_db_health,
                trigger=IntervalTrigger(minutes=10),  # بررسی هر 10 دقیقه
                id='db_health_check_job',
                replace_existing=True
            )

            # اضافه کردن بررسی وضعیت لاگین و سلامت سشن
            self.scheduler.add_job(
                self.check_login_health,
                trigger=IntervalTrigger(hours=2),  # بررسی هر 2 ساعت
                id='login_health_check_job',
                replace_existing=True
            )

            # اضافه کردن بررسی کلی و تنظیم وزن‌های فعالیت‌ها
            self.scheduler.add_job(
                self.dynamically_adjust_activity_weights,
                # هر ساعت وزن‌ها را تنظیم می‌کنیم
                trigger=IntervalTrigger(hours=1),
                id='adjust_weights_job',
                replace_existing=True
            )

            # ریست کردن وضعیت استراحت
            self.is_resting = False
            self.rest_start_time = None
            self.rest_duration = 0
            self.lock_acquired_time = None
            self.restart_attempts = 0
            self.error_count = 0
            self.error_reset_time = datetime.now(timezone.utc)
            self.last_successful_activity = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            self.scheduler.start()
            self.running = True
            logger.info("Bot scheduler started")

            # اجرای یک فعالیت اولیه بلافاصله پس از شروع با تاخیر کم
            first_activity_delay = random.randint(
                30, 180)  # بین 30 ثانیه تا 3 دقیقه
            self.scheduler.add_job(
                self.perform_activity,
                trigger='date',
                run_date=datetime.now() + timedelta(seconds=first_activity_delay),
                id='initial_job'
            )
            logger.info(
                f"Scheduled initial activity for {first_activity_delay} seconds from now")

            return True
        except Exception as e:
            if "database" in str(e).lower() or "sql" in str(e).lower() or "operational" in str(e).lower():
                self._handle_db_error("start", e)
            else:
                logger.error(f"Error starting scheduler: {str(e)}")
                logger.error(traceback.format_exc())
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
                delay = min(60 * self.restart_attempts, 600)  # حداکثر 10 دقیقه
                logger.warning(
                    f"Multiple restart attempts detected ({self.restart_attempts}). Waiting {delay} seconds before trying again...")
                time.sleep(delay)

            # اول به طور کامل متوقف می‌کنیم
            if self.running:
                logger.info("Stopping current scheduler...")
                self.stop()
                # کمی صبر می‌کنیم تا به طور کامل بسته شود
                time.sleep(10)

            # راه‌اندازی مجدد
            logger.info("Starting new scheduler...")
            result = self.start()

            if result:
                self.restart_attempts = 0  # ریست کردن شمارنده در صورت موفقیت
                logger.info("Bot successfully restarted")
                # ریست شمارشگر خطاها
                self.error_count = 0
                self.consecutive_errors = 0
                # بروزرسانی وضعیت سلامت
                self.health_status["errors_since_restart"] = 0
                self.health_status["last_error"] = None
            else:
                logger.error("Failed to restart bot")

            return result

        except Exception as e:
            logger.error(f"Error during bot restart: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def check_login_health(self):
        """Check if the login session is still valid and refresh if needed"""
        try:
            logger.info("Checking login session health...")

            # بررسی وضعیت ورود
            if not self.client.logged_in:
                logger.warning(
                    "Login session appears to be inactive. Attempting to login...")
                login_result = self.client.login(force=True)
                if login_result:
                    logger.info("Successfully refreshed login session")
                    return True
                else:
                    logger.error("Failed to refresh login session")
                    return False

            # حتی اگر ظاهراً لاگین هستیم، یک عملیات ساده انجام دهیم تا مطمئن شویم
            try:
                # یک عملیات ساده که به احتمال زیاد با محدودیت‌های اینستاگرام برخورد نمی‌کند
                # تست اعتبار نشست با استفاده از متد verify_session
                session_valid = self.verify_session_health()

                if session_valid:
                    logger.info("Login session is healthy")
                    return True
                else:
                    # در صورت خطا، دوباره لاگین کنیم
                    logger.warning(
                        "Session check failed. Attempting to login again...")
                    login_result = self.client.login(force=True)
                    if login_result:
                        logger.info(
                            "Successfully refreshed login session after check")
                        return True
                    else:
                        logger.error(
                            "Failed to refresh login session after check")
                        return False
            except Exception as check_error:
                logger.warning(f"Error checking session: {str(check_error)}")

                # در صورت هر خطایی، دوباره لاگین کنیم
                logger.warning(
                    "Session check failed. Attempting to login again...")
                login_result = self.client.login(force=True)
                if login_result:
                    logger.info(
                        "Successfully refreshed login session after check")
                    return True
                else:
                    logger.error("Failed to refresh login session after check")
                    return False

        except Exception as e:
            logger.error(f"Error in login health check: {str(e)}")
            return False

    def monitor_lock_status(self):
        """Monitor lock status and release if necessary, also checks for inactive bot"""
        try:
            # بررسی عدم فعالیت طولانی مدت بات
            if self.last_successful_activity:
                current_time = datetime.now(timezone.utc)
                inactive_time = (
                    current_time - self.last_successful_activity).total_seconds()

                # اگر بیش از 6 ساعت بدون فعالیت موفق گذشته، راه‌اندازی مجدد
                if inactive_time > 21600:  # 6 ساعت
                    logger.warning(
                        f"Bot has been inactive for {inactive_time/3600:.1f} hours. Attempting to restart...")
                    self.restart()
                    return

            # بررسی اگر استراحت در حال انجام است و زمان آن گذشته
            if self.is_resting and self.rest_start_time and self.rest_duration > 0:
                # اطمینان از وجود timezone یکسان برای هر دو زمان
                if self.rest_start_time.tzinfo:
                    current_time = datetime.now(timezone.utc)
                else:
                    current_time = datetime.now()

                elapsed_time = (
                    current_time - self.rest_start_time).total_seconds()

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

            # بررسی اگر قفل گرفته شده و بیش از حد معقول گذشته
            elif self.lock.locked() and self.lock_acquired_time:
                # اطمینان از سازگاری timezone
                if self.lock_acquired_time.tzinfo:
                    current_time = datetime.now(timezone.utc)
                else:
                    current_time = datetime.now()

                elapsed_time = (
                    current_time - self.lock_acquired_time).total_seconds()

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
        """Perform a bot activity based on schedule and limits with adaptive error handling"""
        # استراتژی استراحت بر اساس تعداد خطاها
        # اگر خطاهای متوالی زیاد باشد، احتمال استراحت را افزایش می‌دهیم
        if self.error_count >= 5 and random.random() < 0.7:  # 70% chance of rest
            logger.warning(
                f"Taking a forced rest due to high error count ({self.error_count})")
            self.is_resting = True
            self.rest_start_time = datetime.now(timezone.utc)

            # زمان استراحت طولانی‌تر بسته به تعداد خطاها (بین 1 تا 3 ساعت)
            hours = min(1 + (self.error_count / 5), 3)
            self.rest_duration = hours * 3600
            logger.info(
                f"Setting extended rest period for {hours:.1f} hours due to errors")
            return

        # بررسی وضعیت استراحت قبل از تلاش برای گرفتن قفل
        if self.is_resting:
            # استفاده از datetime.now با timezone
            current_time = datetime.now(timezone.utc)
            if self.rest_start_time and self.rest_start_time.tzinfo is None:
                # اگر rest_start_time بدون timezone است، آن را به timezone.utc تبدیل می‌کنیم
                self.rest_start_time = self.rest_start_time.replace(
                    tzinfo=timezone.utc)

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

        # افزایش timeout برای قفل
        try:
            lock_acquired = self.lock.acquire(blocking=True, timeout=20)
            if not lock_acquired:
                logger.warning(
                    "Could not acquire lock after 20 seconds, another activity might be in progress")
                return

            # ذخیره زمان گرفتن قفل با timezone
            self.lock_acquired_time = datetime.now(timezone.utc)
            logger.info("Lock acquired, preparing to perform activity")

            # اضافه کردن تاخیر تصادفی قبل از شروع
            wait_time = random.randint(5, 15)
            logger.info(
                f"Waiting {wait_time} seconds before starting activity...")
            time.sleep(wait_time)

            # بررسی نیاز به login مجدد
            if not self.client.logged_in:
                logger.info(
                    "Session appears to be expired, attempting to login again...")
                login_result = self.client.login()
                if not login_result:
                    logger.error("Failed to login, skipping activity")
                    # آزاد کردن قفل
                    self.lock.release()
                    self.lock_acquired_time = None
                    # استراحت طولانی‌تر قبل از تلاش بعدی
                    self.is_resting = True
                    self.rest_start_time = datetime.now(timezone.utc)
                    self.rest_duration = 1800  # 30 دقیقه استراحت
                    logger.info(
                        f"Taking a 30 minute break after login failure")
                    return

            # بررسی نیاز به استراحت - احتمال متغیر بر اساس شرایط
            rest_probability = 0.2  # احتمال پایه 20%

            # افزایش احتمال استراحت بر اساس تعداد خطاها
            if self.error_count > 0:
                # افزایش تا حداکثر 50%
                rest_probability += min(self.error_count * 0.1, 0.5)

            # افزایش احتمال استراحت در ساعات شلوغ (ساعت‌های 10 صبح تا 10 شب به وقت ایران)
            current_hour = (datetime.now(timezone.utc).hour +
                            3.5) % 24  # تبدیل به وقت ایران
            if 10 <= current_hour <= 22:
                rest_probability += 0.1

            if random.random() < rest_probability:
                logger.info("Decision made to take a rest")

                # تنظیم وضعیت استراحت
                self.is_resting = True
                self.rest_start_time = datetime.now(timezone.utc)

                # استراحت طولانی‌تر برای جلوگیری از محدودیت‌های اینستاگرام
                # بین 20 تا 90 دقیقه، با احتمال کم برای استراحت‌های طولانی‌تر
                if random.random() < 0.2:  # 20% احتمال استراحت طولانی
                    rest_minutes = random.uniform(60, 180)  # بین 1 تا 3 ساعت
                    logger.info("Taking a longer rest period")
                else:
                    rest_minutes = random.uniform(20, 90)  # بین 20 تا 90 دقیقه

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

            # تنظیم مجدد وزن‌های فعالیت برای این اجرا
            self.dynamically_adjust_activity_weights()

            # انتخاب فعالیت با وزن‌های هوشمند
            activities = []
            weights = []

            for act, weight in self.activity_weights.items():
                activities.append(act)
                weights.append(weight)

            # انتخاب فعالیت با توجه به وزن‌ها
            activity = random.choices(activities, weights=weights, k=1)[0]

            logger.info(f"Performing activity: {activity}")
            # اضافه کردن تخمین زمان پایان فعالیت
            estimated_completion_time = datetime.now(
                timezone.utc) + timedelta(minutes=3)  # تخمین بهتر
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

            # فعالیت موفق - ثبت زمان
            self.last_successful_activity = datetime.now(timezone.utc)
            self.health_status["last_successful_activity"] = self.last_successful_activity.isoformat(
            )

            # کاهش شمارنده خطا در صورت موفقیت
            if self.error_count > 0:
                self.error_count -= 0.5
                if self.error_count < 0:
                    self.error_count = 0

            # ریست شمارنده خطاهای متوالی
            self.consecutive_errors = 0

            # محاسبه و لاگ زمان فعالیت بعدی - فاصله متغیر بین فعالیت‌ها بر اساس شرایط
            if self.error_count > 3:
                # فاصله بیشتر در صورت وجود خطاهای متوالی
                next_minutes = random.randint(30, 60)
            else:
                # فاصله عادی
                next_minutes = random.randint(20, 40)

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
                logger.error(traceback.format_exc())

                # افزایش شمارنده خطاها
                self.error_count += 1
                self.consecutive_errors += 1
                self.health_status["errors_since_restart"] += 1
                self.health_status["last_error"] = f"Activity error: {str(e)}"

                # افزودن ثبت خطا در مانیتور
                rate_limit_indicators = [
                    "login_required", "loginrequired", "please wait", "rate limit", "too many", "timeout"]
                if any(error_text in str(e).lower() for error_text in rate_limit_indicators):
                    logger.warning(
                        "Rate limit or login issue detected, will take a long break")

                    # تنظیم یک استراحت طولانی‌تر در صورت برخورد با محدودیت
                    self.is_resting = True
                    self.rest_start_time = datetime.now(timezone.utc)

                    # مدت استراحت بر اساس تعداد خطاها
                    if self.error_count < 3:
                        self.rest_duration = random.randint(
                            2700, 3600)  # 45-60 دقیقه
                    elif self.error_count < 6:
                        self.rest_duration = random.randint(
                            3600, 7200)  # 1-2 ساعت
                    else:
                        self.rest_duration = random.randint(
                            7200, 14400)  # 2-4 ساعت

                    logger.info(
                        f"Setting extended rest period for {self.rest_duration/60:.1f} minutes due to rate limits (error count: {self.error_count})")

                    if 'bot_monitor' in globals():
                        bot_monitor.record_error(str(e))
                    else:
                        logger.warning(
                            "Bot monitor not available to record error")

                # اگر خطا مربوط به نشست بود، سعی در ورود مجدد
                if "login_required" in str(e).lower() or "loginrequired" in str(e).lower():
                    logger.info(
                        "Session expired. Attempting to login again after delay...")
                    time.sleep(300)  # 5 دقیقه تاخیر قبل از تلاش مجدد
                    self.client.login(force=True)
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
                logger.error(traceback.format_exc())
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
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
                # تغییر زمان آنفالو به بین 21 تا 30 روز
                days = random.randint(21, 30)
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
                logger.error(traceback.format_exc())
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
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
                logger.error(traceback.format_exc())
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
                        bot_monitor.record_error(
                            f"Like activity error: {str(e)}")

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
                logger.error(traceback.format_exc())
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
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
                logger.error(traceback.format_exc())
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
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
                logger.error(traceback.format_exc())
                # ثبت خطا در مانیتور
                if any(error_text in str(e).lower() for error_text in ["login_required", "please wait", "rate limit"]):
                    if 'bot_monitor' in globals():
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
                logger.error(traceback.format_exc())
