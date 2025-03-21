import time
import random
import logging
from datetime import datetime, timezone, timedelta

from app.logger import setup_logger

# Setup logger
logger = setup_logger("rate_limit")


class RateLimitHandler:
    """کلاس مدیریت محدودیت نرخ درخواست برای API اینستاگرام"""

    def __init__(self):
        # زمان آخرین درخواست‌ها به تفکیک نوع عملیات
        self.last_request_times = {
            "like": None,
            "follow": None,
            "unfollow": None,
            "comment": None,
            "direct": None,
            "story_reaction": None,
            "feed": None,
            "profile": None,
            "media": None,
            "generic": None
        }

        # تعداد درخواست‌های هر عملیات در ساعت
        self.hourly_counts = {k: 0 for k in self.last_request_times.keys()}

        # زمان ریست شمارنده‌های ساعتی
        self.hourly_reset_time = datetime.now(timezone.utc)

        # محدودیت‌های پایه برای هر عملیات در ساعت
        self.hourly_limits = {
            "like": 30,          # حداکثر 60 لایک در ساعت
            "follow": 10,        # حداکثر 20 فالو در ساعت
            "unfollow": 10,      # حداکثر 20 آنفالو در ساعت
            "comment": 15,       # حداکثر 15 کامنت در ساعت
            "direct": 10,        # حداکثر 10 پیام مستقیم در ساعت
            "story_reaction": 30,  # حداکثر 30 واکنش به استوری در ساعت
            "feed": 100,         # حداکثر 100 درخواست feed در ساعت
            "profile": 100,      # حداکثر 100 بازدید پروفایل در ساعت
            "media": 100,        # حداکثر 100 بازدید مدیا در ساعت
            "generic": 200       # سایر درخواست‌ها
        }

        # حداقل فاصله زمانی بین درخواست‌های متوالی (به ثانیه)
        self.min_delay = {
            "like": 24,          # حداقل 24 ثانیه بین لایک‌ها
            "follow": 38,        # حداقل 38 ثانیه بین فالوها
            "unfollow": 38,      # حداقل 38 ثانیه بین آنفالوها
            "comment": 45,       # حداقل 45 ثانیه بین کامنت‌ها
            "direct": 60,        # حداقل 60 ثانیه بین پیام‌های مستقیم
            "story_reaction": 30,  # حداقل 30 ثانیه بین واکنش‌های استوری
            "feed": 10,          # حداقل 10 ثانیه بین درخواست‌های feed
            "profile": 15,       # حداقل 15 ثانیه بین بازدیدهای پروفایل
            "media": 15,         # حداقل 15 ثانیه بین بازدیدهای مدیا
            "generic": 5         # حداقل 5 ثانیه بین سایر درخواست‌ها
        }

        # وضعیت فعلی محدودیت
        self.is_rate_limited = False
        self.rate_limit_until = None

        # شمارنده خطاهای محدودیت
        self.rate_limit_errors = 0
        self.last_error_time = None

    def reset_hourly_counts(self):
        """ریست کردن شمارنده‌های ساعتی"""
        now = datetime.now(timezone.utc)
        if (now - self.hourly_reset_time).total_seconds() >= 3600:  # گذشت 1 ساعت
            self.hourly_counts = {k: 0 for k in self.hourly_counts.keys()}
            self.hourly_reset_time = now
            logger.info("Hourly request counts reset")

    def can_proceed(self, operation_type):
        """بررسی اینکه آیا می‌توان عملیات را انجام داد یا باید صبر کرد"""
        if operation_type not in self.last_request_times:
            operation_type = "generic"

        # ریست شمارنده‌های ساعتی در صورت نیاز
        self.reset_hourly_counts()

        # بررسی وضعیت محدودیت کلی
        now = datetime.now(timezone.utc)
        if self.is_rate_limited and self.rate_limit_until and now < self.rate_limit_until:
            remaining = (self.rate_limit_until - now).total_seconds()
            logger.warning(
                f"Global rate limit active. {remaining:.0f} seconds remaining")
            return False, remaining

        # بررسی محدودیت ساعتی
        if self.hourly_counts[operation_type] >= self.hourly_limits[operation_type]:
            seconds_until_reset = 3600 - \
                (now - self.hourly_reset_time).total_seconds()
            logger.warning(
                f"Hourly limit reached for {operation_type}. Wait {seconds_until_reset:.0f} seconds")
            return False, seconds_until_reset

        # بررسی فاصله زمانی بین درخواست‌های متوالی
        if self.last_request_times[operation_type]:
            elapsed = (
                now - self.last_request_times[operation_type]).total_seconds()
            min_required = self.min_delay[operation_type]

            if elapsed < min_required:
                wait_time = min_required - elapsed
                logger.info(
                    f"Need to wait {wait_time:.1f} seconds before next {operation_type}")
                return False, wait_time

        # اضافه کردن تاخیر تصادفی بیشتر برای طبیعی‌تر بودن
        jitter = random.uniform(1, 10)
        time.sleep(jitter)

        return True, 0

    def log_request(self, operation_type):
        """ثبت یک درخواست انجام شده"""
        if operation_type not in self.last_request_times:
            operation_type = "generic"

        self.last_request_times[operation_type] = datetime.now(timezone.utc)
        self.hourly_counts[operation_type] += 1

    def handle_rate_limit_error(self, error_message):
        """مدیریت خطای محدودیت نرخ درخواست"""
        now = datetime.now(timezone.utc)
        self.rate_limit_errors += 1
        self.last_error_time = now

        # ریست شمارنده خطا پس از یک ساعت
        if self.last_error_time and (now - self.last_error_time).total_seconds() > 3600:
            self.rate_limit_errors = 1  # شروع از 1 (خطای فعلی)

        # محاسبه مدت زمان محدودیت بر اساس تعداد خطاها
        if "wait a few minutes" in error_message.lower():
            # برای خطای "Please wait a few minutes"
            if self.rate_limit_errors <= 1:
                wait_minutes = random.randint(15, 30)  # 15-30 دقیقه
            elif self.rate_limit_errors <= 3:
                wait_minutes = random.randint(30, 60)  # 30-60 دقیقه
            else:
                wait_minutes = random.randint(60, 180)  # 1-3 ساعت
        else:
            # برای سایر خطاهای محدودیت
            if self.rate_limit_errors <= 1:
                wait_minutes = random.randint(5, 15)  # 5-15 دقیقه
            elif self.rate_limit_errors <= 3:
                wait_minutes = random.randint(15, 45)  # 15-45 دقیقه
            else:
                wait_minutes = random.randint(45, 120)  # 45-120 دقیقه

        self.is_rate_limited = True
        self.rate_limit_until = now + timedelta(minutes=wait_minutes)

        logger.warning(
            f"Rate limit triggered. Waiting for {wait_minutes} minutes")
        return wait_minutes * 60  # بازگرداندن زمان محدودیت به ثانیه

    def clear_rate_limit(self):
        """پاک کردن وضعیت محدودیت در صورت موفقیت عملیات"""
        if self.is_rate_limited:
            self.is_rate_limited = False
            self.rate_limit_until = None
            logger.info("Rate limit cleared after successful operation")

        # کاهش تدریجی شمارنده خطا
        if self.rate_limit_errors > 0:
            self.rate_limit_errors -= 0.5
            if self.rate_limit_errors < 0:
                self.rate_limit_errors = 0


# Create a global instance for use across the application
rate_limit_handler = RateLimitHandler()
