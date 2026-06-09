import os
import time
import logging
import signal
import asyncio
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands, tasks

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("selfbot")



# Bot client (user account - bot=False)


# Environment variables with defaults
TOKEN = os.getenv("DISCORD_TOKEN")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
COMMAND_NAME = os.getenv("COMMAND_NAME", "bump").lower()
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "120"))
MAX_FAILURES = int(os.getenv("MAX_FAILURES", "3"))

# State variables
last_bump_time: float = 0
bump_failures: int = 0
command_cache: Optional[discord.app_commands.Command] = None

@client.event
async def on_ready():
    logger.info(f"Logged in as {client.user} (ID: {client.user.id})")
    logger.info(f"Target guild: {TARGET_GUILD_ID}")
    logger.info(f"Target channel: {CHANNEL_ID}")
    logger.info(f"Command: /{COMMAND_NAME}")
    logger.info(f"Interval: {INTERVAL_MINUTES} minutes")
    
    # Verify we can access the guild and channel
    guild = client.get_guild(TARGET_GUILD_ID)
    if not guild:
        logger.error(f"❌ Cannot access guild {TARGET_GUILD_ID}. Make sure the bot is in the server.")
    else:
        logger.info(f"✅ Guild accessible: {guild.name}")
        
        channel = guild.get_channel(CHANNEL_ID)
        if not channel:
            logger.error(f"❌ Cannot access channel {CHANNEL_ID}")
        else:
            logger.info(f"✅ Channel accessible: {channel.name}")
    
    # Prefetch command and start periodic task
    await prefetch_command()
    start_periodic_task()

async def prefetch_command():
    """Fetch and cache the slash command."""
    global command_cache
    try:
        guild = client.get_guild(TARGET_GUILD_ID)
        if not guild:
            logger.error(f"Guild {TARGET_GUILD_ID} not found")
            return False
        
        # Fetch global and guild commands
        global_commands = await client.fetch_global_commands()
        guild_commands = await guild.fetch_commands()
        
        # Search in both global and guild commands
        all_commands = list(global_commands) + list(guild_commands)
        command = next((c for c in all_commands if c.name.lower() == COMMAND_NAME), None)
        
        if not command:
            logger.error(f"Command /{COMMAND_NAME} not found in guild {TARGET_GUILD_ID}")
            logger.info(f"Available commands: {[c.name for c in all_commands]}")
            return False
        
        command_cache = command
        logger.info(f"✅ Cached command /{COMMAND_NAME} (ID: {command.id})")
        return True
        
    except Exception as e:
        logger.error(f"Error fetching command: {e}")
        return False

@tasks.loop(minutes=INTERVAL_MINUTES)
async def periodic_bump():
    """Execute the slash command every interval."""
    global last_bump_time, bump_failures, command_cache
    
    try:
        # Check failure count
        if bump_failures >= MAX_FAILURES:
            logger.error(f"❌ Max failures ({MAX_FAILURES}) reached. Stopping task.")
            periodic_bump.stop()
            return
        
        # Get channel
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            logger.error(f"❌ Channel {CHANNEL_ID} not found")
            bump_failures += 1
            return
        
        # Ensure command is cached
        if not command_cache:
            if not await prefetch_command():
                logger.error("❌ Command unavailable after prefetch attempt")
                bump_failures += 1
                return
        
        # Execute the command
        logger.info(f"🔄 Executing /{COMMAND_NAME} at {datetime.utcnow().isoformat()}")
        
        # Method 1: Send as a message (most reliable for self-bots)
        await channel.send(f"/{COMMAND_NAME}")
        
        # Method 2: Alternative - use direct command invocation (if supported)
        # try:
        #     await client.get_guild(TARGET_GUILD_ID).invoke(command_cache)
        # except Exception as e:
        #     logger.warning(f"Direct invocation failed: {e}")
        #     await channel.send(f"/{COMMAND_NAME}")
        
        last_bump_time = time.time()
        bump_failures = 0  # Reset on success
        logger.info(f"✅ Command executed successfully")
        
    except discord.HTTPException as e:
        if e.status == 429:  # Rate limited
            retry_after = e.retry_after or 60
            logger.warning(f"⚠️ Rate limited. Retrying in {retry_after}s")
            await asyncio.sleep(retry_after)
            await periodic_bump.retry()
        else:
            logger.error(f"❌ HTTP Error {e.status}: {e.text}")
            bump_failures += 1
            
    except discord.NotFound:
        logger.error(f"❌ Command /{COMMAND_NAME} not found in guild {TARGET_GUILD_ID}")
        bump_failures += 1
        command_cache = None
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {type(e).__name__}: {e}")
        bump_failures += 1

def start_periodic_task():
    """Start the periodic bump task."""
    if not periodic_bump.is_running():
        periodic_bump.start()
        logger.info(f"✅ Started periodic task: /{COMMAND_NAME} every {INTERVAL_MINUTES} minutes")

async def shutdown(signame):
    """Graceful shutdown handler."""
    logger.info(f"🛑 Received {signame}. Shutting down...")
    periodic_bump.stop()
    await client.close()
    logger.info("✅ Self-bot shutdown complete")

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for signame in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda s=signame: asyncio.create_task(shutdown(s))
        )

async def main():
    """Main entry point."""
    setup_signal_handlers()
    
    if not TOKEN:
        logger.error("❌ DISCORD_TOKEN environment variable not set!")
        return
    
    try:
        await client.start(TOKEN)
    except Exception as e:
        logger.error(f"❌ Fatal error: {type(e).__name__}: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
