import logging
import uvicorn
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models.database import create_tables, get_db
from app.bot.scheduler import BotScheduler
from app.api.routes import router as api_router
from app.config import API_HOST, API_PORT
import app.api.routes as routes_module

# افزودن کتابخانه‌های مورد نیاز برای محدودیت درخواست
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# تعریف محدودکننده درخواست
limiter = Limiter(key_func=get_remote_address)

# کلاس میدلور برای افزودن هدرهای امنیتی


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # هدرهای امنیتی برای جلوگیری از حملات متداول
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

# میدلور برای فیلتر کردن درخواست‌های مشکوک


async def filter_suspicious_requests(request: Request, call_next):
    path = request.url.path.lower()
    suspicious_patterns = [
        ".git", ".env", "wp-", "phpinfo", ".php", "config",
        "admin", "shell", ".htaccess", "passwd", "ssh",
        "credential", ".aws", "api/proxy", "eval", "exec"
    ]

    # بررسی الگوهای مشکوک در مسیر
    if any(pattern in path for pattern in suspicious_patterns):
        logger.warning(
            f"Suspicious request blocked: {request.client.host} - {path}")
        return JSONResponse(
            status_code=403,
            content={"detail": "Access forbidden"}
        )

    return await call_next(request)

# Create FastAPI app
app = FastAPI(
    title="Instagram Bot API",
    description="API for controlling Instagram bot with human-like behavior",
    version="1.0.0"
)

# اضافه کردن میدلویر‌ها
app.middleware("http")(filter_suspicious_requests)
app.add_middleware(SecurityHeadersMiddleware)

# تنظیم محدودکننده درخواست
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add API routes
app.include_router(api_router)


@app.on_event("startup")
async def startup_event():
    """Initialize the application on startup"""
    try:
        # Create database tables
        create_tables()
        logger.info("Database tables created successfully")

        # Initialize bot scheduler
        try:
            db = next(get_db())
            bot_scheduler = BotScheduler(db)

            # Make bot scheduler available to API routes
            routes_module.bot_scheduler = bot_scheduler

            # Start the bot automatically if enabled
            # Uncomment this part after confirming API works
            # success = bot_scheduler.start()
            # if success:
            #     logger.info("Bot started successfully")
            # else:
            #     logger.error("Failed to start bot")
            logger.info("Bot scheduler initialized but not auto-started")

        except Exception as e:
            logger.error(f"Error initializing bot scheduler: {str(e)}")
            raise

    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise


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
