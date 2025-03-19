import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from instagrapi.exceptions import UserNotFound, ClientError

from app.models.database import BotActivity, UserFollowing, DailyStats
from app.config import DAILY_UNFOLLOW_LIMIT
from app.logger import setup_logger

# Configure logging
logger = setup_logger("unfollow_action")


class UnfollowAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db

    def get_daily_unfollow_count(self):
        """Get the number of unfollows for today"""
        today = datetime.utcnow().date()
        stats = self.db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if stats:
            return stats.unfollows_count
        return 0

    def can_perform_action(self):
        """Check if we can perform an unfollow action today"""
        unfollows_count = self.get_daily_unfollow_count()
        return unfollows_count < DAILY_UNFOLLOW_LIMIT

    def unfollow_user(self, user_id):
        """Unfollow a specific user by user_id"""
        try:
            # Check if we're following this user
            user_info = self.client.user_info(user_id)
            username = user_info.username

            # Check if we have a record for this user
            existing_record = self.db.query(UserFollowing).filter(
                UserFollowing.user_id == user_id
            ).first()

            if existing_record and not existing_record.is_following:
                logger.info(f"Already unfollowed user {username} ({user_id})")
                return False

            # Unfollow the user
            result = self.client.user_unfollow(user_id)

            if result:
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
                    existing_record.unfollowed_at = datetime.utcnow()
                else:
                    following = UserFollowing(
                        user_id=user_id,
                        username=username,
                        is_following=False,
                        unfollowed_at=datetime.utcnow()
                    )
                    self.db.add(following)

                # Update daily stats
                today = datetime.utcnow().date()
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

        except (UserNotFound, ClientError) as e:
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
            logger.error(f"Error unfollowing user {user_id}: {str(e)}")
            return False

    def unfollow_non_followers(self, max_users=10):
        """Unfollow users who don't follow us back"""
        if not self.can_perform_action():
            logger.info(
                f"Daily unfollow limit reached: {DAILY_UNFOLLOW_LIMIT}")
            return 0

        try:
            # Get my user ID
            user_id = self.client.user_id

            # Get my followers
            my_followers = self.client.user_followers(user_id)

            # Get users I'm following
            my_following = self.client.user_following(user_id)

            # Find users I follow but they don't follow back
            not_following_me_back = set(
                my_following.keys()) - set(my_followers.keys())

            unfollowed_count = 0
            # Convert to list and shuffle
            not_following_me_back_list = list(not_following_me_back)
            random.shuffle(not_following_me_back_list)

            for user_id in not_following_me_back_list[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

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
            threshold_date = datetime.utcnow() - timedelta(days=days_threshold)

            # Get my followers for checking who doesn't follow back
            user_id = self.client.user_id
            my_followers = self.client.user_followers(user_id)
            follower_ids = set(my_followers.keys())

            # Find users we've been following for more than X days who didn't follow back
            old_followings = self.db.query(UserFollowing).filter(
                UserFollowing.is_following == True,
                UserFollowing.followed_at <= threshold_date,
                UserFollowing.followed_back == False
            ).limit(max_users * 2).all()

            unfollowed_count = 0
            # Shuffle the results to make it more human-like
            random.shuffle(old_followings)

            for following in old_followings[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Check if they actually follow us now (might have changed since our last check)
                is_follower = following.user_id in follower_ids

                if is_follower:
                    # Update record if they now follow us
                    following.followed_back = True
                    self.db.commit()
                    continue

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
            user_id = self.client.user_id

            # Get my current followers
            my_followers = self.client.user_followers(user_id)
            follower_ids = set(my_followers.keys())

            # Find users who had followed back but might have unfollowed us
            potential_unfollowers = self.db.query(UserFollowing).filter(
                UserFollowing.is_following == True,
                UserFollowing.followed_back == True
            ).limit(max_users * 3).all()

            unfollowed_count = 0
            # Shuffle the results
            random.shuffle(potential_unfollowers)

            for following in potential_unfollowers[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Check if they still follow us
                still_follows = following.user_id in follower_ids

                if not still_follows:
                    # They unfollowed us, so unfollow them back
                    if self.unfollow_user(following.user_id):
                        unfollowed_count += 1

            return unfollowed_count

        except Exception as e:
            logger.error(
                f"Error unfollowing users who unfollowed me: {str(e)}")
            return 0
