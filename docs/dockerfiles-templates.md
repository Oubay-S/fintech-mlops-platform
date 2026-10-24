# Official Dockerfile Templates & Containerization Standards

> **Author:** Role 3 (DevOps / MLOps)  
> **Audience:** Role 1 (Backend), Role 2 (Frontend), Role 5 (ML Serving)  
> **Purpose:** Standardized multi-stage Dockerfiles, security hardening, and layer caching optimization.

Every microservice container must adhere to the **Service Image Checklist** in [docs/conventions.md](conventions.md) and [APPLICATION_CONCEPTION_PLAN V2.1 Section 24.1](../APPLICATION_CONCEPTION_PLAN%20V2.1.md).

---

## 1. Spring Boot Microservices (Java 21) — Role 1 & Role 2

Place this file at `services/<service-name>/Dockerfile`.

### Features
- **Multi-Stage Build:** Uses full Maven image for compilation, then copies only the minimal runnable JAR to a lightweight JRE Alpine image.
- **Layer Caching:** Copies `pom.xml` and downloads dependencies (`go-offline`) *before* copying source code. Edits to Java code will not re-download the internet!
- **Security:** Runs as non-root user `appuser` (UID `1001`).
- **Memory Management:** Injects `-XX:MaxRAMPercentage=75` to prevent JVM from exceeding Kubernetes container memory limits and triggering OOMKills.

```dockerfile
# ------------------------------------------------------------------------------
# Stage 1: Build Application
# ------------------------------------------------------------------------------
FROM maven:3.9-eclipse-temurin-21-alpine AS builder

WORKDIR /build

# Cache dependencies
COPY pom.xml .
RUN mvn dependency:go-offline -B

# Compile and package JAR
COPY src ./src
RUN mvn clean package -DskipTests -B

# ------------------------------------------------------------------------------
# Stage 2: Minimal Runtime Environment
# ------------------------------------------------------------------------------
FROM eclipse-temurin:21-jre-alpine AS runner

WORKDIR /app

# Create non-root system group and user
RUN addgroup -g 1001 -S appgroup && \
    adduser -S appuser -u 1001 -G appgroup

# Copy compiled JAR with correct permissions
COPY --from=builder --chown=appuser:appgroup /build/target/*.jar app.jar

# Run as non-root user
USER 1001

# JVM container memory tuning (APPLICATION_CONCEPTION Section 24.1)
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseG1GC -Djava.security.egd=file:/dev/./urandom"

# Documented port (override with environment variable if needed)
EXPOSE 8080

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
```

### Accompanying `.dockerignore` (`services/<service-name>/.dockerignore`)
```
target/
.git/
.idea/
*.iml
.vscode/
*.log
```

---

## 2. FastAPI ML Serving (Python 3.11) — Role 5

Place this file at `ml/serving/Dockerfile`.

### Features
- **Security:** Dedicated non-root user `mluser` (UID `1001`).
- **Caching:** Installs `requirements.txt` before copying application code.
- **Minimal Footprint:** Uses `python:3.11-slim`, disables pip cache.

```dockerfile
# ------------------------------------------------------------------------------
# Runtime Environment
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

WORKDIR /app

# Create non-root user
RUN useradd -u 1001 -m -s /bin/bash mluser

# Install Python dependencies first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy service source code and model stubs
COPY . .
RUN chown -R mluser:mluser /app

# Run as non-root user
USER 1001

# FastAPI default port
EXPOSE 8000

# Start Uvicorn production server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### Accompanying `.dockerignore` (`ml/serving/.dockerignore`)
```
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.venv/
venv/
.git/
.env*
```

---

## 3. React Frontend Dashboard (Nginx Alpine) — Role 2

Place this file at `frontend/Dockerfile`.

### Features
- **Multi-Stage Build:** Compiles TypeScript + React in Node.js 20, then serves static HTML/JS/CSS through Nginx Alpine (final image < 25 MB).
- **SPA Routing:** Configured Nginx to route all subpaths to `index.html`.

```dockerfile
# ------------------------------------------------------------------------------
# Stage 1: Build React SPA
# ------------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Cache NPM packages
COPY package*.json ./
RUN npm ci

# Build static bundle
COPY . .
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 2: Serve with Nginx Alpine
# ------------------------------------------------------------------------------
FROM nginx:alpine AS runner

# Remove default nginx welcome page
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration for Single Page Application (SPA) routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### Accompanying `frontend/nginx.conf`
```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # Proxy API calls directly in standalone Docker Compose setups
    location /api/ {
        proxy_pass http://api-gateway:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 4. Verification Commands for Developers

Before opening a PR, test your container image locally:

```bash
# 1. Build image
docker build -t fintech-test-service .

# 2. Run container
docker run --rm -p <port>:<port> fintech-test-service

# 3. Verify health endpoint in another terminal
curl http://localhost:<port>/health
# Or for Spring Boot:
curl http://localhost:<port>/actuator/health
```
