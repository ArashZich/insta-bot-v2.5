import logging
import uvicorn
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.models.database import create_tables, get_db
from app.bot.scheduler import BotScheduler
from app.api.routes import router as api_router
from app.config import API_HOST, API_PORT
import app.api.routes as routes_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Instagram Bot API",
    description="API for controlling Instagram bot with human-like behavior",
    version="1.0.0"
)

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
        db = next(get_db())
        bot_scheduler = BotScheduler(db)

        # Make bot scheduler available to API routes
        routes_module.bot_scheduler = bot_scheduler

        # Start the bot automatically
        success = bot_scheduler.start()
        if success:
            logger.info("Bot started successfully")
        else:
            logger.error("Failed to start bot")

    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")


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
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=False)
