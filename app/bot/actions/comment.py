
import random
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_COMMENT_LIMIT
from app.data.responses import COMMENTS
from app.logger import setup_logger

# Configure logging
logger = setup_logger("comment_action")


class CommentAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db

    def get_daily_comment_count(self):
        """Get the number of comments for today"""
        today = datetime.now(timezone.utc).date()
        stats = self.db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if stats:
            return stats.comments_count
        return 0

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

    def comment_on_media(self, media_id, text=None, user_id=None, username=None):
        """Comment on a specific media by media_id"""
        try:
            # Get media info if user info not provided
            if not user_id or not username:
                media_info = self.client.media_info(media_id)
                user_id = media_info.user.pk
                username = media_info.user.username

                # Get comment text if not provided
                if not text:
                    caption = media_info.caption_text if media_info.caption_text else ""
                    text = self.get_appropriate_comment(
                        media_info.media_type, caption)
            elif not text:
                text = self.get_appropriate_comment()

            # Comment on the media
            result = self.client.media_comment(media_id, text)

            if result:
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

        except ClientError as e:
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
            logger.error(f"Error commenting on media {media_id}: {str(e)}")
            return False

    def comment_on_hashtag_medias(self, hashtag, max_comments=3):
        """Comment on posts with a specific hashtag"""
        if not self.can_perform_action():
            logger.info(f"Daily comment limit reached: {DAILY_COMMENT_LIMIT}")
            return 0

        try:
            # Get medias by hashtag
            medias = self.client.hashtag_medias_recent(
                hashtag, max_comments * 3)

            commented_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            for media in medias[:max_comments]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                user_id = media.user.pk
                username = media.user.username
                caption = media.caption_text if media.caption_text else ""

                # Generate appropriate comment
                comment_text = self.get_appropriate_comment(
                    media.media_type, caption)

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
            user_id = self.client.user_id

            # Get my followers
            my_followers = self.client.user_followers(user_id)

            commented_count = 0
            # Convert to list and shuffle
            follower_ids = list(my_followers.keys())
            random.shuffle(follower_ids)

            for follower_id in follower_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Get user's media
                try:
                    medias = self.client.user_medias(follower_id, 5)
                    if medias:
                        # Get a random media
                        media = random.choice(medias)
                        username = self.client.user_info(follower_id).username
                        caption = media.caption_text if media.caption_text else ""

                        # Generate appropriate comment
                        comment_text = self.get_appropriate_comment(
                            media.media_type, caption)

                        # Comment on the media
                        if self.comment_on_media(media.id, comment_text, follower_id, username):
                            commented_count += 1
                except Exception as e:
                    logger.warning(
                        f"Could not get media for user {follower_id}: {str(e)}")
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
            # Get feed medias
            feed_items = self.client.get_timeline_feed()
            medias = []

            # Extract medias from feed items
            for item in feed_items:
                if hasattr(item, 'media_or_ad'):
                    medias.append(item.media_or_ad)

            commented_count = 0
            # Shuffle to make it more human-like
            random.shuffle(medias)

            for media in medias[:max_comments]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                user_id = media.user.pk
                username = media.user.username
                caption = media.caption_text if media.caption_text else ""

                # Generate appropriate comment
                comment_text = self.get_appropriate_comment(
                    media.media_type, caption)

                # Comment on the media
                if self.comment_on_media(media.id, comment_text, user_id, username):
                    commented_count += 1

            return commented_count

        except Exception as e:
            logger.error(f"Error commenting on feed medias: {str(e)}")
            return 0
