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


def get_date_range_from_period(period: str):
    """Convert period string to date range"""
    now = datetime.utcnow()
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period == "yesterday":
        start_date = (now - timedelta(days=1)).replace(hour=0,
                                                       minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_week":
        # Get the start of the current week (Monday)
        start_date = (now - timedelta(days=now.weekday())
                      ).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period == "last_week":
        # Get the start of the last week (Monday)
        this_week_start = (now - timedelta(days=now.weekday())
                           ).replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = this_week_start - timedelta(days=7)
        end_date = this_week_start
    elif period == "this_month":
        # Get the start of the current month
        start_date = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period == "last_month":
        # Get the start of the current month
        this_month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        # Get the start of the last month (handle year change)
        if this_month_start.month == 1:
            start_date = this_month_start.replace(
                year=this_month_start.year-1, month=12)
        else:
            start_date = this_month_start.replace(
                month=this_month_start.month-1)
        end_date = this_month_start
    elif period == "last_30_days":
        start_date = now - timedelta(days=30)
        end_date = now
    elif period == "last_90_days":
        start_date = now - timedelta(days=90)
        end_date = now
    elif period == "this_year":
        start_date = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period == "all_time":
        start_date = datetime.min
        end_date = now
    else:
        # Default to last 7 days if period is unknown
        start_date = now - timedelta(days=7)
        end_date = now

    return start_date, end_date


@router.get("/activities", response_model=ActivityListResponse)
def get_activities(
    activity_type: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = Query(
        "last_7_days", description="Time period filter [today, yesterday, this_week, last_week, this_month, last_month, last_30_days, last_90_days, this_year, all_time]"),
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

    # Apply date filters
    # If from_date and to_date are explicitly provided, use them
    # Otherwise, use the period parameter
    if from_date or to_date:
        if from_date:
            query = query.filter(BotActivity.created_at >= from_date)
        if to_date:
            query = query.filter(BotActivity.created_at <= to_date)
    elif period:
        start_date, end_date = get_date_range_from_period(period)
        query = query.filter(BotActivity.created_at >= start_date)
        query = query.filter(BotActivity.created_at <= end_date)

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
    period: Optional[str] = Query(
        "last_7_days", description="Time period filter [today, yesterday, this_week, last_week, this_month, last_month, last_30_days, last_90_days, this_year, all_time]"),
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

    # Apply date filters
    # If from_date and to_date are explicitly provided, use them
    # Otherwise, use the period parameter
    if from_date or to_date:
        if from_date:
            query = query.filter(UserFollowing.followed_at >= from_date)
        if to_date:
            query = query.filter(UserFollowing.followed_at <= to_date)
    elif period:
        start_date, end_date = get_date_range_from_period(period)
        query = query.filter(UserFollowing.followed_at >= start_date)
        query = query.filter(UserFollowing.followed_at <= end_date)

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
