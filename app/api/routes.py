from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta

from app.models.database import get_db, BotActivity, UserFollowing, BotSession, DailyStats
from app.bot.utils import get_activity_stats, get_daily_limits_status
from app.api.schemas import (
    StatsRequest,
    StatsResponse,
    BotStatusResponse,
    BotControlRequest,
    BotControlResponse,
    ActivityCount,
    ActivityItem,
    ActivityListResponse,
    FollowingItem,
    FollowingListResponse
)

# Create the API router
router = APIRouter(prefix="/api", tags=["bot"])

# Reference to bot scheduler will be set in main.py
bot_scheduler = None


@router.get("/status", response_model=BotStatusResponse)
def get_bot_status(db: Session = Depends(get_db)):
    """Get current bot status"""
    # Check if bot is running
    running = bot_scheduler.running if bot_scheduler else False

    # Check if logged in
    logged_in = bot_scheduler.client.logged_in if bot_scheduler else False

    # Check if session is active
    session_active = False
    if db:
        session = db.query(BotSession).filter(
            BotSession.is_active == True
        ).first()
        session_active = session is not None

    # Get daily limits
    daily_limits = get_daily_limits_status(db)

    # Get last activity
    last_activity = None
    if db:
        activity = db.query(BotActivity).order_by(
            BotActivity.created_at.desc()
        ).first()
        if activity:
            last_activity = activity.created_at

    return BotStatusResponse(
        running=running,
        logged_in=logged_in,
        session_active=session_active,
        daily_limits=ActivityCount(**daily_limits),
        last_activity=last_activity
    )


@router.post("/control", response_model=BotControlResponse)
def control_bot(request: BotControlRequest):
    """Control bot (start, stop, restart)"""
    if not bot_scheduler:
        raise HTTPException(
            status_code=503, detail="Bot scheduler not initialized")

    action = request.action.lower()

    if action == "start":
        if bot_scheduler.running:
            return BotControlResponse(
                success=False,
                message="Bot is already running",
                status=True
            )
        else:
            success = bot_scheduler.start()
            return BotControlResponse(
                success=success,
                message="Bot started successfully" if success else "Failed to start bot",
                status=success
            )

    elif action == "stop":
        if not bot_scheduler.running:
            return BotControlResponse(
                success=False,
                message="Bot is not running",
                status=False
            )
        else:
            bot_scheduler.stop()
            return BotControlResponse(
                success=True,
                message="Bot stopped successfully",
                status=False
            )

    elif action == "restart":
        if bot_scheduler.running:
            bot_scheduler.stop()

        success = bot_scheduler.start()
        return BotControlResponse(
            success=success,
            message="Bot restarted successfully" if success else "Failed to restart bot",
            status=success
        )

    else:
        raise HTTPException(
            status_code=400, detail="Invalid action. Use 'start', 'stop', or 'restart'")


@router.post("/stats", response_model=StatsResponse)
def get_stats(request: StatsRequest, db: Session = Depends(get_db)):
    """Get bot statistics for a specific period"""
    period = request.period.lower()

    if period not in ["daily", "weekly", "monthly", "six_months"]:
        raise HTTPException(
            status_code=400, detail="Invalid period. Use 'daily', 'weekly', 'monthly', or 'six_months'")

    stats = get_activity_stats(db, period)

    return StatsResponse(period=period, **stats)


@router.get("/activities", response_model=ActivityListResponse)
def get_activities(
    activity_type: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get bot activities with filtering options"""
    query = db.query(BotActivity)

    # Apply filters
    if activity_type:
        query = query.filter(BotActivity.activity_type == activity_type)

    if status:
        query = query.filter(BotActivity.status == status)

    if from_date:
        query = query.filter(BotActivity.created_at >= from_date)

    if to_date:
        query = query.filter(BotActivity.created_at <= to_date)

    # Count total matching records
    total = query.count()

    # Apply pagination
    query = query.order_by(BotActivity.created_at.desc())
    query = query.offset((page - 1) * size).limit(size)

    # Convert to response model
    activities = [
        ActivityItem(
            id=activity.id,
            activity_type=activity.activity_type,
            target_user_id=activity.target_user_id,
            target_user_username=activity.target_user_username,
            target_media_id=activity.target_media_id,
            status=activity.status,
            details=activity.details,
            created_at=activity.created_at
        )
        for activity in query.all()
    ]

    return ActivityListResponse(
        activities=activities,
        total=total,
        page=page,
        size=size
    )


@router.get("/followings", response_model=FollowingListResponse)
def get_followings(
    is_following: Optional[bool] = None,
    followed_back: Optional[bool] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get user followings with filtering options"""
    query = db.query(UserFollowing)

    # Apply filters
    if is_following is not None:
        query = query.filter(UserFollowing.is_following == is_following)

    if followed_back is not None:
        query = query.filter(UserFollowing.followed_back == followed_back)

    if from_date:
        query = query.filter(UserFollowing.followed_at >= from_date)

    if to_date:
        query = query.filter(UserFollowing.followed_at <= to_date)

    # Count total matching records
    total = query.count()

    # Apply pagination
    query = query.order_by(UserFollowing.followed_at.desc())
    query = query.offset((page - 1) * size).limit(size)

    # Convert to response model
    followings = [
        FollowingItem(
            id=following.id,
            user_id=following.user_id,
            username=following.username,
            followed_at=following.followed_at,
            unfollowed_at=following.unfollowed_at,
            is_following=following.is_following,
            followed_back=following.followed_back
        )
        for following in query.all()
    ]

    return FollowingListResponse(
        followings=followings,
        total=total,
        page=page,
        size=size
    )
