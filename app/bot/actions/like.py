
import random
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_LIKE_LIMIT
from app.logger import setup_logger

# Configure logging
logger = setup_logger("like_action")


class LikeAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db

    def get_daily_like_count(self):
        """Get the number of likes for today"""
        today = datetime.now(timezone.utc).date()
        stats = self.db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if stats:
            return stats.likes_count
        return 0

    def can_perform_action(self):
        """Check if we can perform a like action today"""
        likes_count = self.get_daily_like_count()
        return likes_count < DAILY_LIKE_LIMIT

    def like_media(self, media_id, user_id=None, username=None):
        """Like a specific media by media_id"""
        try:
            # Like the media
            result = self.client.media_like(media_id)

            # Get user info if not provided
            if not user_id or not username:
                media_info = self.client.media_info(media_id)
                user_id = media_info.user.pk
                username = media_info.user.username

            if result:
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

        except ClientError as e:
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
            logger.error(f"Error liking media {media_id}: {str(e)}")
            return False

    def like_user_media(self, user_id, max_likes=3):
        """Like multiple posts from a specific user"""
        if not self.can_perform_action():
            logger.info(f"Daily like limit reached: {DAILY_LIKE_LIMIT}")
            return 0

        try:
            # Get user info
            user_info = self.client.user_info(user_id)
            username = user_info.username

            # Get user medias
            medias = self.client.user_medias(
                user_id, 20)  # Fetch 20 recent posts

            liked_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            for media in medias[:max_likes]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

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
            # Get medias by hashtag
            medias = self.client.hashtag_medias_recent(hashtag, max_likes * 3)

            liked_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            for media in medias[:max_likes]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

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
            user_id = self.client.user_id

            # Get my followers
            my_followers = self.client.user_followers(user_id)

            liked_count = 0
            # Convert to list and shuffle
            follower_ids = list(my_followers.keys())
            random.shuffle(follower_ids)

            for follower_id in follower_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Like user's media
                liked_for_user = self.like_user_media(
                    follower_id, posts_per_user)
                liked_count += liked_for_user

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
            # Get feed medias
            feed_items = self.client.get_timeline_feed()
            medias = []

            # Extract medias from feed items
            for item in feed_items:
                if hasattr(item, 'media_or_ad'):
                    medias.append(item.media_or_ad)

            liked_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            for media in medias[:max_likes]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                user_id = media.user.pk
                username = media.user.username

                # Like the media
                if self.like_media(media.id, user_id, username):
                    liked_count += 1

            return liked_count

        except Exception as e:
            logger.error(f"Error liking feed medias: {str(e)}")
            return 0
