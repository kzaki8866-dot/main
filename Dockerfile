# Use Python 3.11 (compatible with discord.py-self 2.1.0)
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create non-root user for security
RUN useradd -m selfbotuser && chown -R selfbotuser: /app
USER selfbotuser

# Set environment variables (can be overridden in Render)
ENV DISCORD_TOKEN=""
ENV TARGET_GUILD_ID="0"
ENV CHANNEL_ID="0"
ENV COMMAND_NAME="bump"
ENV INTERVAL_MINUTES="120"
ENV MAX_FAILURES="3"

# Health check (optional)
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import os; os.environ.get('DISCORD_TOKEN') or exit(1)"

# Run the application
CMD ["python", "main.py"]
