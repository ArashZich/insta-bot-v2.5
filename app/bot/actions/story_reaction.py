import random
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError, PleaseWaitFewMinutes, LoginRequired, RateLimitError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_STORY_REACTION_LIMIT
from app.data.responses import STORY_REACTIONS
from app.logger import setup_logger
from app.bot.rate_limit import rate_limit_handler

# Configure logging
logger = setup_logger("story_reaction_action")


class StoryReactionAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db
        self.error_count = 0
        self.retry_delay = 30  # تاخیر اولیه برای تلاش مجدد (ثانیه)

    def get_daily_story_reaction_count(self):
        """Get the number of story reactions for today"""
        try:
            today = datetime.now(timezone.utc).date()
            stats = self.db.query(DailyStats).filter(
                DailyStats.date >= today
            ).first()

            if stats:
                return stats.story_reactions_count
            return 0
        except Exception as e:
            logger.error(f"Error getting daily story reaction count: {str(e)}")
            # در صورت خطا، مقدار محافظه‌کارانه برگردانیم
            return DAILY_STORY_REACTION_LIMIT - 2

    def can_perform_action(self):
        """Check if we can perform a story reaction action today"""
        reactions_count = self.get_daily_story_reaction_count()
        return reactions_count < DAILY_STORY_REACTION_LIMIT

    def get_random_reaction(self, story_content=None):
        """Get a random reaction emoji or text"""
        if not STORY_REACTIONS:
            return "👍"

        # Default to emoji reactions
        reaction_type = 'emoji'

        # Randomly decide to use text reaction sometimes
        if random.random() < 0.3:  # 30% chance of using text
            reaction_type = 'text'

        # Choose reaction from the appropriate type
        if reaction_type in STORY_REACTIONS and STORY_REACTIONS[reaction_type]:
            reactions = STORY_REACTIONS[reaction_type]
            return random.choice(reactions)
        else:
            # Default fallback reactions
            emoji_defaults = ["❤️", "👍", "🔥", "👏", "😍"]
            text_defaults = ["عالی", "خیلی خوب", "جالبه", "قشنگه"]

            return random.choice(emoji_defaults if reaction_type == 'emoji' else text_defaults)

    def react_to_story(self, story_id, text=None, user_id=None, username=None, retry_count=0):
        """React to a specific story by story_id with improved error handling"""
        # بررسی محدودیت نرخ درخواست
        can_proceed, wait_time = rate_limit_handler.can_proceed(
            "story_reaction")
        if not can_proceed:
            logger.info(
                f"Rate limit check suggests waiting {wait_time:.1f} seconds before reacting to story")
            if wait_time > 0:
                time.sleep(min(wait_time, 60))  # صبر کنیم، حداکثر 60 ثانیه

        try:
            # Get story info if user info not provided
            if not user_id or not username:
                # Note: instagrapi doesn't provide a direct method to get story info by ID
                # So we'll have to work with what we have
                # In a real scenario, we'd likely already have this info from fetching stories

                # For the sake of this example, we'll assume we don't have the info
                # and we'll use placeholder values if not provided
                user_id = user_id or "unknown"
                username = username or "unknown"

            # Get reaction text if not provided
            if not text:
                text = self.get_random_reaction()

            # ثبت درخواست در مدیریت کننده محدودیت
            rate_limit_handler.log_request("story_reaction")

            # React to the story
            result = self.client.story_send_reaction(story_id, [text])

            if result:
                # ثبت موفقیت در مدیریت کننده محدودیت
                rate_limit_handler.clear_rate_limit()

                # ریست شمارنده خطا
                self.error_count = 0

                # Record the activity
                activity = BotActivity(
                    activity_type="story_reaction",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=story_id,
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
                    stats.story_reactions_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        story_reactions_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully reacted to story {story_id} of user {username}")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="story_reaction",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=story_id,
                    status="failed",
                    details=f"Story reaction failed: {text}"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(f"Failed to react to story {story_id}")
                return False

        except (PleaseWaitFewMinutes, RateLimitError) as e:
            # محدودیت نرخ درخواست
            error_message = str(e)
            logger.warning(
                f"Rate limit hit during story reaction operation: {error_message}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="story_reaction",
                target_user_id=user_id,
                target_user_username=username,
                target_media_id=story_id,
                status="failed",
                details=f"Rate limit error: {error_message}, Reaction: {text if text else 'None'}"
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
                    f"Will retry reacting to story after {wait_seconds} seconds")
                # حداکثر 5 دقیقه صبر می‌کنیم
                time.sleep(min(wait_seconds, 300))
                return self.react_to_story(story_id, text, user_id, username, retry_count + 1)

            return False

        except LoginRequired as e:
            # خطای نیاز به لاگین مجدد
            logger.error(
                f"Login required during story reaction operation: {str(e)}")

            # ثبت فعالیت ناموفق
            activity = BotActivity(
                activity_type="story_reaction",
                target_user_id=user_id,
                target_user_username=username,
                target_media_id=story_id,
                status="failed",
                details=f"Login error: {str(e)}, Reaction: {text if text else 'None'}"
            )
            self.db.add(activity)
            self.db.commit()
            return False

        except ClientError as e:
            # سایر خطاهای کلاینت
            logger.error(f"Error reacting to story {story_id}: {str(e)}")

            # Record the error
            activity = BotActivity(
                activity_type="story_reaction",
                target_user_id=user_id,
                target_user_username=username,
                target_media_id=story_id,
                status="failed",
                details=f"Error: {str(e)}, Reaction: {text if text else 'None'}"
            )
            self.db.add(activity)
            self.db.commit()

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

        except Exception as e:
            # سایر خطاهای غیرمنتظره
            logger.error(
                f"Unexpected error reacting to story {story_id}: {str(e)}")

            try:
                # Record the error
                activity = BotActivity(
                    activity_type="story_reaction",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=story_id,
                    status="failed",
                    details=f"Unexpected error: {str(e)}, Reaction: {text if text else 'None'}"
                )
                self.db.add(activity)
                self.db.commit()
            except Exception as db_error:
                logger.error(
                    f"Error recording story reaction failure: {str(db_error)}")

            # افزایش شمارنده خطا
            self.error_count += 1
            return False

    def react_to_user_stories(self, user_id, max_reactions=2):
        """React to stories from a specific user"""
        if not self.can_perform_action():
            logger.info(
                f"Daily story reaction limit reached: {DAILY_STORY_REACTION_LIMIT}")
            return 0

        try:
            # Get user info
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                user_info = self.client.user_info(user_id)
                username = user_info.username
            except Exception as e:
                logger.error(
                    f"Error getting user info for {user_id}: {str(e)}")
                username = "unknown"

            # Get user stories
            try:
                # ثبت درخواست در مدیریت کننده محدودیت
                rate_limit_handler.log_request("profile")

                stories = self.client.user_stories(user_id)

                if not stories:
                    logger.info(
                        f"No stories found for user {username} ({user_id})")
                    return 0
            except Exception as e:
                logger.error(
                    f"Error getting stories for user {user_id}: {str(e)}")
                return 0

            reacted_count = 0
            # Shuffle to make it more human-like
            random.shuffle(stories)

            # افزودن تأخیر کوتاه قبل از شروع واکنش‌ها
            time.sleep(random.uniform(3, 7))

            for story in stories[:max_reactions]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily story reaction limit reached during operation: {DAILY_STORY_REACTION_LIMIT}")
                    break

                # Get random reaction
                reaction = self.get_random_reaction()

                # افزودن تأخیر تصادفی بین واکنش‌ها
                if reacted_count > 0:
                    delay = random.uniform(30, 60)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before next story reaction")
                    time.sleep(delay)

                # React to the story
                if self.react_to_story(story.id, reaction, user_id, username):
                    reacted_count += 1

            return reacted_count

        except Exception as e:
            logger.error(
                f"Error reacting to stories for user {user_id}: {str(e)}")
            return 0

    def react_to_followers_stories(self, max_users=3, max_reactions_per_user=1):
        """React to stories from users who follow us"""
        if not self.can_perform_action():
            logger.info(
                f"Daily story reaction limit reached: {DAILY_STORY_REACTION_LIMIT}")
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
                logger.error(f"Error getting followers: {str(e)}")
                return 0

            reacted_count = 0
            # Convert to list and shuffle
            follower_ids = list(my_followers.keys())
            random.shuffle(follower_ids)

            # افزودن تأخیر کوتاه قبل از شروع فرآیند
            time.sleep(random.uniform(3, 7))

            for follower_id in follower_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily story reaction limit reached during followers operation: {DAILY_STORY_REACTION_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین پردازش هر فالوئر
                if reacted_count > 0:
                    delay = random.uniform(30, 60)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before processing next follower's stories")
                    time.sleep(delay)

                # React to user's stories
                reacted_for_user = self.react_to_user_stories(
                    follower_id, max_reactions_per_user)
                reacted_count += reacted_for_user

            return reacted_count

        except Exception as e:
            logger.error(f"Error reacting to followers stories: {str(e)}")
            return 0

    def react_to_following_stories(self, max_users=5, max_reactions_per_user=1):
        """React to stories from users we follow"""
        if not self.can_perform_action():
            logger.info(
                f"Daily story reaction limit reached: {DAILY_STORY_REACTION_LIMIT}")
            return 0

        try:
            # Get my user ID
            try:
                user_id = self.client.user_id
            except Exception as e:
                logger.error(f"Error getting user_id: {str(e)}")
                return 0

            # Get users I'm following
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

            reacted_count = 0
            # Convert to list and shuffle
            following_ids = list(my_following.keys())
            random.shuffle(following_ids)

            # افزودن تأخیر کوتاه قبل از شروع فرآیند
            time.sleep(random.uniform(3, 7))

            for following_id in following_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    logger.info(
                        f"Daily story reaction limit reached during following operation: {DAILY_STORY_REACTION_LIMIT}")
                    break

                # افزودن تأخیر تصادفی بین پردازش هر فالویینگ
                if reacted_count > 0:
                    delay = random.uniform(30, 60)
                    logger.info(
                        f"Waiting {delay:.1f} seconds before processing next following's stories")
                    time.sleep(delay)

                # React to user's stories
                reacted_for_user = self.react_to_user_stories(
                    following_id, max_reactions_per_user)
                reacted_count += reacted_for_user

            return reacted_count

        except Exception as e:
            logger.error(f"Error reacting to following stories: {str(e)}")
            return 0
