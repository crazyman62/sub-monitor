# Use official Python lightweight image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FLASK_APP=app.app
ENV DATABASE_PATH="sqlite:////data/emby_manager.db"

# Create working directory
WORKDIR /app

# Install system dependencies (if any are needed for specific python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Create data directory for volume mapping
RUN mkdir /data

# Copy project
COPY . /app/

# Expose port
EXPOSE 5005

# Run gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "app.app:app", "--workers", "1", "--threads", "2", "--timeout", "60"]
