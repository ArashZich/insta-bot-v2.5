import requests
import logging
import time
from datetime import datetime, timedelta, timezone
from app.logger import setup_logger

# Setup logger
logger = setup_logger("bot_monitor")


class BotMonitor:
    def __init__(self, error_threshold=15, time_window_minutes=30):
        self.error_count = 0
        self.error_timestamps = []
        self.error_threshold = error_threshold
        self.time_window = timedelta(minutes=time_window_minutes)
        self.last_restart_time = None
        # حداقل 15 دقیقه بین راه‌اندازی‌های مجدد
        self.restart_cooldown = timedelta(minutes=15)

    def record_error(self, error_message):
        """ثبت یک خطا و بررسی نیاز به راه‌اندازی مجدد"""
        now = datetime.now(timezone.utc)

        # افزودن زمان خطا به لیست
        self.error_timestamps.append(now)

        # حذف خطاهای قدیمی خارج از پنجره زمانی
        self.error_timestamps = [
            t for t in self.error_timestamps if now - t <= self.time_window]

        # بررسی تعداد خطاها در پنجره زمانی
        self.error_count = len(self.error_timestamps)

        logger.warning(
            f"Bot error detected: {error_message}. Current error count: {self.error_count}/{self.error_threshold}")

        # بررسی آیا نیاز به راه‌اندازی مجدد است
        if self.error_count >= self.error_threshold:
            return self.restart_bot()

        return False

    def restart_bot(self):
        """راه‌اندازی مجدد ربات اگر از زمان آخرین راه‌اندازی مجدد زمان کافی گذشته باشد"""
        now = datetime.now(timezone.utc)

        # بررسی زمان آخرین راه‌اندازی مجدد
        if self.last_restart_time and now - self.last_restart_time < self.restart_cooldown:
            logger.info("Skipping restart due to cooldown period")
            return False

        try:
            logger.warning(
                f"Error threshold reached ({self.error_count} errors in the last {self.time_window.total_seconds()/60} minutes). Attempting to restart bot...")

            # فراخوانی API راه‌اندازی مجدد
            response = requests.get(
                "http://localhost:8000/api/restart-bot", timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.info("Bot restarted successfully via API")
                    self.last_restart_time = now
                    self.error_count = 0
                    self.error_timestamps = []
                    return True
                else:
                    logger.error(
                        f"Bot restart failed: {result.get('message', 'Unknown error')}")
                    return False
            else:
                logger.error(
                    f"Failed to restart bot. API returned status code: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Exception during bot restart attempt: {str(e)}")

            # اگر نتوانستیم از طریق API راه‌اندازی مجدد کنیم، به عنوان پشتیبان تلاش کنیم از force-unlock استفاده کنیم
            try:
                unlock_response = requests.get(
                    "http://localhost:8000/api/force-unlock", timeout=10)
                logger.info(
                    f"Force unlock response: {unlock_response.status_code}")
                return False
            except:
                logger.error("Failed to force unlock as fallback")
                return False


# ایجاد یک نمونه جهانی از مانیتور
bot_monitor = BotMonitor(error_threshold=10, time_window_minutes=15)
