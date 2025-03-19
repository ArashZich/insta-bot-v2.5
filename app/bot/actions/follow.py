import random
from datetime import datetime
from sqlalchemy.orm import Session
from instagrapi.exceptions import UserNotFound, ClientError

from app.models.database import BotActivity, UserFollowing, DailyStats
from app.config import DAILY_FOLLOW_LIMIT
from app.logger import setup_logger

# Configure logging
logger = setup_logger("follow_action")


class FollowAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db

    def get_daily_follow_count(self):
        """Get the number of follows for today"""
        today = datetime.utcnow().date()
        stats = self.db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if stats:
            return stats.follows_count
        return 0

    def can_perform_action(self):
        """Check if we can perform a follow action today"""
        follows_count = self.get_daily_follow_count()
        return follows_count < DAILY_FOLLOW_LIMIT

    def follow_user(self, user_id):
        """Follow a specific user by user_id"""
        try:
            # Check if already following
            user_info = self.client.user_info(user_id)
            username = user_info.username

            # Check if we already have a record for this user
            existing_record = self.db.query(UserFollowing).filter(
                UserFollowing.user_id == user_id
            ).first()

            if existing_record and existing_record.is_following:
                logger.info(f"Already following user {username} ({user_id})")
                return False

            # Follow the user
            result = self.client.user_follow(user_id)

            if result:
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
                    existing_record.followed_at = datetime.utcnow()
                    existing_record.unfollowed_at = None
                else:
                    following = UserFollowing(
                        user_id=user_id,
                        username=username,
                        is_following=True
                    )
                    self.db.add(following)

                # Update daily stats
                today = datetime.utcnow().date()
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

        except (UserNotFound, ClientError) as e:
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
            logger.error(f"Error following user {user_id}: {str(e)}")
            return False

    def follow_hashtag_users(self, hashtag, max_users=5):
        """Follow users who posted with the given hashtag"""
        if not self.can_perform_action():
            logger.info(f"Daily follow limit reached: {DAILY_FOLLOW_LIMIT}")
            return 0

        try:
            # Get medias by hashtag
            medias = self.client.hashtag_medias_recent(hashtag, max_users * 3)

            followed_count = 0
            random.shuffle(medias)  # Randomize to make it more human-like

            for media in medias[:max_users]:
                user_id = media.user.pk

                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

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
            target_user_id = self.client.user_id_from_username(target_username)

            # Get followers
            followers = self.client.user_followers(
                target_user_id, max_users * 2)

            followed_count = 0
            # Convert to list and shuffle to make it more human-like
            follower_ids = list(followers.keys())
            random.shuffle(follower_ids)

            for user_id in follower_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

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
            user_id = self.client.user_id

            # Get my followers
            my_followers = self.client.user_followers(user_id)

            # Get users I'm following
            my_following = self.client.user_following(user_id)

            # Find users who follow me but I don't follow back
            not_following_back = set(
                my_followers.keys()) - set(my_following.keys())

            followed_count = 0
            # Convert to list and shuffle
            not_following_back_list = list(not_following_back)
            random.shuffle(not_following_back_list)

            for user_id in not_following_back_list[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Follow the user
                if self.follow_user(user_id):
                    followed_count += 1

            return followed_count

        except Exception as e:
            logger.error(f"Error following my followers: {str(e)}")
            return 0
