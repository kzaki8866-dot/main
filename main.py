import discord
from discord.ext import tasks, commands
import asyncio
import logging
import os
import signal
import time
from datetime import datetime
from typing import Optional

# Configure logging with timestamps and file output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('selfbot.log')
    ]
)
logger = logging.getLogger('selfbot')

# Intents configuration (minimum required for slash commands)
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

# Initialize client (bot=False for self-bot)
client = commands.Bot(command_prefix='!', intents=intents, bot=False)

# Configuration - set these via environment variables in Render
TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_GUILD_ID = int(os.getenv('TARGET_GUILD_ID', '0'))
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
COMMAND_NAME = os.getenv('COMMAND_NAME', 'bump').lower()

# Periodic task settings
INTERVAL_MINUTES = int(os.getenv('INTERVAL_MINUTES', '120'))
MAX_FAILURES = int(os.getenv('MAX_FAILURES', '3'))

# Global state
last_bump_time = 0
bump_failures = 0
command_cache: Optional[discord.app_commands.Command] = None

@client.event
async def on_ready():
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    logger.info(f'User bot status: {await client.get_user_application() is not None}')

    # Pre-fetch the command during startup
    await prefetch_command()
    start_periodic_task()

async def prefetch_command():
    global command_cache
    try:
        guild = client.get_guild(TARGET_GUILD_ID)
        if not guild:
            logger.error(f"Guild {TARGET_GUILD_ID} not found during prefetch")
            return

        commands = await guild.fetch_commands()
        command = next((c for c in commands if c.name.lower() == COMMAND_NAME), None)

        if not command:
            logger.error(f"Command /{COMMAND_NAME} not found in guild {TARGET_GUILD_ID} during prefetch")
            return

        command_cache = command
        logger.info(f"Prefetched command /{COMMAND_NAME} successfully")

    except Exception as e:
        logger.error(f"Error during command prefetch: {e}")

@tasks.loop(minutes=INTERVAL_MINUTES)
async def periodic_bump():
    global last_bump_time, bump_failures, command_cache

    try:
        if bump_failures >= MAX_FAILURES:
            logger.error(f"Too many failures ({bump_failures}). Stopping periodic task.")
            periodic_bump.stop()
            return

        # Get target channel
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            logger.error(f"Channel {CHANNEL_ID} not found")
            bump_failures += 1
            return

        # Verify command exists (use cache if available)
        if not command_cache:
            await prefetch_command()
            if not command_cache:
                logger.error("Command not available after prefetch attempt")
                bump_failures += 1
                return

        logger.info(f"Executing /{COMMAND_NAME} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Execute the slash command via text input
        await channel.send(f'/{COMMAND_NAME}')
        last_bump_time = time.time()
        bump_failures = 0  # Reset failures on success

    except discord.HTTPException as e:
        if e.status == 429:  # Rate limited
            retry_after = e.retry_after or 60  # Default to 60 seconds if retry_after is None
            logger.warning(f"Rate limited. Retrying in {retry_after} seconds")
            await asyncio.sleep(retry_after)
            await periodic_bump.retry()
        else:
            logger.error(f"HTTP Error: {e.status} - {e.text}")
            bump_failures += 1

    except discord.NotFound:
        logger.error(f"Command /{COMMAND_NAME} not found in guild {TARGET_GUILD_ID}")
        bump_failures += 1
        command_cache = None  # Invalidate cache

    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        bump_failures += 1

def start_periodic_task():
    if not periodic_bump.is_running():
        periodic_bump.start()
        logger.info(f"Started periodic task to run /{COMMAND_NAME} every {INTERVAL_MINUTES} minutes")

async def shutdown(signame):
    logger.info(f"Received {signame}, shutting down...")
    periodic_bump.stop()
    await client.close()
    logger.info("Self-bot shutdown complete")

def setup_signal_handlers():
    for signame in ('SIGINT', 'SIGTERM'):
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda s=signame: asyncio.create_task(shutdown(s))
        )

async def main():
    setup_signal_handlers()
    try:
        await client.start(TOKEN)
    except Exception as e:
        logger.error(f"Fatal error: {type(e).__name__}: {e}")
    finally:
        await client.close()

if __name__ == '__main__':
    asyncio.run(main())


---

### Dockerfile
# Stage 1: Build environment
FROM python:3.11-slim-bookworm as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime environment
FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY main.py .
COPY requirements.txt .

# Set environment variables (can be overridden in Render)
ENV DISCORD_TOKEN=""
ENV TARGET_GUILD_ID="0"
ENV CHANNEL_ID="0"
ENV COMMAND_NAME="bump"
ENV INTERVAL_MINUTES="120"
ENV MAX_FAILURES="3"

# Non-root user for security
RUN useradd -m selfbotuser && \
    chown -R selfbotuser: /app
USER selfbotuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')"

# Command to run the application
CMD ["python", "main.py"]
