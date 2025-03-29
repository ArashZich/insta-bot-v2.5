import asyncio
import os
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse
from sqlalchemy.orm import Session

from app.models.database import create_tables, get_db, Base, engine
from app.bot.scheduler import BotScheduler
from app.api.routes import router as api_router
from app.config import API_HOST, API_PORT
import app.api.routes as routes_module
from app.logger import setup_logger

# Setup logger
logger = setup_logger("main")

# ساخت پوشه استاتیک اگر وجود ندارد
os.makedirs("app/static", exist_ok=True)

# Create FastAPI app
app = FastAPI(
    title="Instagram Bot API",
    description="API for controlling Instagram bot with human-like behavior",
    version="1.0.0"
)

# میدلور ساده برای فیلتر کردن درخواست‌های مشکوک


@app.middleware("http")
async def filter_suspicious_requests(request: Request, call_next):
    path = request.url.path.lower()
    suspicious_patterns = [
        ".git/", ".env", "wp-", "phpinfo", ".php",
        "/.git", "/config", "/admin"
    ]

    # بررسی الگوهای مشکوک در مسیر
    if any(pattern in path for pattern in suspicious_patterns):
        logger.warning(
            f"Suspicious request blocked: {request.client.host} - {path}")
        return JSONResponse(
            status_code=403,
            content={"detail": "Access forbidden"}
        )

    # ادامه پردازش درخواست
    return await call_next(request)

# Add API routes
app.include_router(api_router)

# اضافه کردن مسیر فایل‌های استاتیک
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Route for root path - redirect to control panel


@app.get("/")
async def read_root():
    return FileResponse("app/static/index.html")

# نسخه بهینه شده startup event


@app.on_event("startup")
async def startup_event():
    """Initialize the application on startup"""
    global routes_module

    logger.info("Starting application initialization...")

    # اطمینان از ایجاد دیتابیس
    try:
        # ایجاد جداول دیتابیس
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}")

    # راه‌اندازی scheduler ربات
    try:
        db = next(get_db())
        bot_scheduler = BotScheduler(db)
        routes_module.bot_scheduler = bot_scheduler
        logger.info("Bot scheduler initialized")

        # راه‌اندازی خودکار ربات
        if bot_scheduler.initialize():
            bot_scheduler.start()
            logger.info("Bot started automatically")
        else:
            logger.warning(
                "Bot initialization failed, not starting automatically")
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        try:
            # ایجاد یک نمونه خالی به عنوان fallback
            db = next(get_db())
            routes_module.bot_scheduler = BotScheduler(db)
            logger.warning("Created empty bot scheduler as fallback")
        except Exception as fallback_error:
            logger.critical(
                f"Failed to create fallback scheduler: {str(fallback_error)}")

    logger.info("Application startup completed")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    try:
        # Stop the bot if it's running
        if routes_module.bot_scheduler and routes_module.bot_scheduler.running:
            routes_module.bot_scheduler.stop()
            logger.info("Bot stopped on shutdown")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=API_HOST, port=API_PORT, reload=False)
