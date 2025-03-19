from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class StatsRequest(BaseModel):
    period: str  # 'daily', 'weekly', 'monthly', 'six_months'


class ActivityCount(BaseModel):
    follows: int
    unfollows: int
    likes: int
    comments: int
    directs: int
    story_reactions: int


class StatsResponse(BaseModel):
    period: str
    follows: int
    unfollows: int
    likes: int
    comments: int
    directs: int
    story_reactions: int
    followers_gained: int
    followers_lost: int
    days: int
    avg_follows: Optional[float] = None
    avg_unfollows: Optional[float] = None
    avg_likes: Optional[float] = None
    avg_comments: Optional[float] = None
    avg_directs: Optional[float] = None
    avg_story_reactions: Optional[float] = None
    avg_followers_gained: Optional[float] = None
    avg_followers_lost: Optional[float] = None


class BotStatusResponse(BaseModel):
    running: bool
    logged_in: bool
    session_active: bool
    daily_limits: ActivityCount
    last_activity: Optional[datetime] = None


class BotControlRequest(BaseModel):
    action: str  # 'start', 'stop', 'restart'


class BotControlResponse(BaseModel):
    success: bool
    message: str
    status: bool  # current bot status (running or not)


class ActivityItem(BaseModel):
    id: int
    activity_type: str
    target_user_id: str
    target_user_username: str
    target_media_id: Optional[str] = None
    status: str
    details: Optional[str] = None
    created_at: datetime


class ActivityListResponse(BaseModel):
    activities: List[ActivityItem]
    total: int
    page: int
    size: int


class FollowingItem(BaseModel):
    id: int
    user_id: str
    username: str
    followed_at: datetime
    unfollowed_at: Optional[datetime] = None
    is_following: bool
    followed_back: bool


class FollowingListResponse(BaseModel):
    followings: List[FollowingItem]
    total: int
    page: int
    size: int
