from app.bot.actions.follow import FollowAction
from app.bot.actions.unfollow import UnfollowAction
from app.bot.actions.like import LikeAction
from app.bot.actions.comment import CommentAction
from app.bot.actions.direct import DirectAction
from app.bot.actions.story_reaction import StoryReactionAction


class ActionManager:
    def __init__(self, client, db):
        self.client = client
        self.db = db

        # Initialize all action classes
        self.follow = FollowAction(client, db)
        self.unfollow = UnfollowAction(client, db)
        self.like = LikeAction(client, db)
        self.comment = CommentAction(client, db)
        self.direct = DirectAction(client, db)
        self.story_reaction = StoryReactionAction(client, db)
