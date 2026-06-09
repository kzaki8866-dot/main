 # main.py
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

   # Intents
   intents = discord.Intents.default()
   intents.message_content = True
   intents.guilds = True
   intents.members = True

   # Bot client (user account)
   client = commands.Bot(command_prefix="!", intents=intents, bot=False)

   # Environment variables
   TOKEN = os.getenv("DISCORD_TOKEN")
   TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", "0"))
   CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
   COMMAND_NAME = os.getenv("COMMAND_NAME", "bump").lower()
   INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "120"))
   MAX_FAILURES = int(os.getenv("MAX_FAILURES", "3"))

   # State
   last_bump_time: float = 0
   bump_failures: int = 0
   command_cache: Optional[discord.app_commands.Command] = None

   @client.event
   async def on_ready():
       logger.info(f"Logged in as {client.user} (ID: {client.user.id})")
       await prefetch_command()
       start_periodic_task()

   async def prefetch_command():
       """Fetch the slash command object and cache it."""
       global command_cache
       try:
           guild = client.get_guild(TARGET_GUILD_ID)
           if not guild:
               logger.error(f"Guild {TARGET_GUILD_ID} not found")
               return
           commands = await guild.fetch_commands()
           command = next((c for c in commands if c.name.lower() == COMMAND_NAME), None)
           if not command:
               logger.error(f"Command /{COMMAND_NAME} not found in guild {TARGET_GUILD_ID}")
               return
           command_cache = command
           logger.info(f"Cached command /{COMMAND_NAME}")
       except Exception as e:
           logger.error(f"Error fetching command: {e}")

   @tasks.loop(minutes=INTERVAL_MINUTES)
   async def periodic_bump():
       global last_bump_time, bump_failures, command_cache
       try:
           if bump_failures >= MAX_FAILURES:
               logger.error(f"Exceeded max failures ({MAX_FAILURES}). Stopping task.")
               periodic_bump.stop()
               return

           channel = client.get_channel(CHANNEL_ID)
           if not channel:
               logger.error(f"Channel {CHANNEL_ID} not found")
               bump_failures += 1
               return

           if not command_cache:
               await prefetch_command()
               if not command_cache:
                   logger.error("Command still unavailable after prefetch")
                   bump_failures += 1
                   return

           logger.info(f"Executing /{COMMAND_NAME} at {datetime.utcnow().isoformat()}")
           await channel.send(f"/{COMMAND_NAME}")
           last_bump_time = time.time()
           bump_failures = 0
       except discord.HTTPException as e:
           if e.status == 429:
               retry = e.retry_after or 60
               logger.warning(f"Rate limited. Retrying in {retry}s")
               await asyncio.sleep(retry)
               await periodic_bump.retry()
           else:
               logger.error(f"HTTP error {e.status}: {e.text}")
               bump_failures += 1
       except discord.NotFound:
           logger.error(f"Command /{COMMAND_NAME} not found in guild {TARGET_GUILD_ID}")
           bump_failures += 1
           command_cache = None
       except Exception as e:
           logger.error(f"Unexpected error: {e}")
           bump_failures += 1

   def start_periodic_task():
       if not periodic_bump.is_running():
           periodic_bump.start()
           logger.info(f"Started periodic bump every {INTERVAL_MINUTES} minutes")

   async def shutdown(signame):
       logger.info(f"Received {signame}. Shutting down.")
       periodic_bump.stop()
       await client.close()

   def setup_signal_handlers():
       loop = asyncio.get_event_loop()
       for signame in ("SIGINT", "SIGTERM"):
           loop.add_signal_handler(
               getattr(signal, signame),
               lambda s=signame: asyncio.create_task(shutdown(s))
           )

   async def main():
       setup_signal_handlers()
       try:
           await client.start(TOKEN)
       except Exception as e:
           logger.error(f"Fatal error: {e}")
       finally:
           await client.close()

   if __name__ == "__main__":
       asyncio.run(main())
