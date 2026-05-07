# Task ID: 11

**Title:** Create Production Docker Configuration

**Status:** pending

**Dependencies:** None

**Priority:** medium

**Description:** Create Dockerfile and docker-compose.yml for production deployment with Postgres backend.

**Details:**

1. Create `Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install uv

# Copy dependency files
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies
RUN uv pip install --system -e .

# Copy brand configs
COPY brands/ ./brands/
COPY config/ ./config/

# Create data directory
RUN mkdir -p /app/data

EXPOSE 8501

ENTRYPOINT ["resound"]
CMD ["run", "--brand", "liquiddeath"]
```

2. Create `docker-compose.yml`:
```yaml
version: '3.8'
services:
  resound:
    build: .
    env_file: .env
    environment:
      - RESOUND_DATABASE_URL=postgresql+psycopg://resound:resound@db:5432/resound
    depends_on:
      - db
    volumes:
      - ./data:/app/data
      - ./brands:/app/brands:ro
    command: run --brand ${RESOUND_BRAND:-liquiddeath}
  
  dashboard:
    build: .
    env_file: .env
    environment:
      - RESOUND_DATABASE_URL=postgresql+psycopg://resound:resound@db:5432/resound
    depends_on:
      - db
    ports:
      - "8501:8501"
    command: dashboard --brand ${RESOUND_BRAND:-liquiddeath}
  
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: resound
      POSTGRES_PASSWORD: resound
      POSTGRES_DB: resound
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U resound"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

3. Update `.env.example` with production settings documentation

4. Add healthcheck endpoint to CLI or dashboard

**Test Strategy:**

Manual testing:
- Test `docker compose build` succeeds
- Test `docker compose up` starts all services
- Test dashboard accessible at localhost:8501
- Test pipeline writes to Postgres (check with psql)
- Test container restart preserves data
- Test with different RESOUND_BRAND values
