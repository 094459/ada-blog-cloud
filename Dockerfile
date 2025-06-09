FROM --platform=$TARGETPLATFORM python:3.9-slim

# Add build arguments for platform detection
ARG TARGETPLATFORM
ARG BUILDPLATFORM
RUN echo "I am running on $BUILDPLATFORM, building for $TARGETPLATFORM"

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements_s3.txt .
RUN pip install --no-cache-dir -r requirements_s3.txt

# Copy application code
COPY app_s3.py .
COPY templates/ ./templates/
COPY static/ ./static/

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app_s3.py

# Expose port
EXPOSE 5000

# Run the application
CMD ["flask", "run", "--host=0.0.0.0"]
