# Stage 1: Build the Application
FROM python:3.11-slim AS build

WORKDIR /usr/src/app/backend

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the backend source code
COPY backend/ /usr/src/app/backend/

# Stage 2: Create the Final Production Image
FROM python:3.11-slim

WORKDIR /usr/src/app/backend

# Install runtime dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the build stage
COPY --from=build /opt/venv /opt/venv

# Copy the application code
COPY --from=build /usr/src/app/backend /usr/src/app/backend

# Set the virtual environment as the active Python environment
ENV PATH="/opt/venv/bin:$PATH"

# Create a non-root user to run the application
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /usr/src/app
USER appuser

# Expose the port your app runs on
ENV PORT=8080
EXPOSE 8080

# Define the command to start your application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
