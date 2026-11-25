# ==============================================================================
# FinTech Platform — single parameterized Spring Boot image
#
# Build context MUST be the `services/` directory (the Maven reactor root),
# because every service inherits `com.fintech:fintech-parent` and depends on
# the `platform-starter` module:
#
#   docker buildx build \
#     -f infra/docker/services/Dockerfile \
#     --build-arg SERVICE=auth-service \
#     --build-arg SERVICE_PORT=8081 \
#     -t fintech-auth-service:dev \
#     services/
#
# Add a new service: add its `COPY` target to the reactor (nothing else here)
# and add it to the CI matrix in .github/workflows/ci.yml.
# ==============================================================================
FROM maven:3.9-eclipse-temurin-21-alpine AS builder

ARG SERVICE
WORKDIR /build

# The whole reactor is required: the parent POM declares every module, and
# `-am` builds platform-starter as a dependency of the target service.
COPY . .

# BuildKit cache mount keeps ~/.m2 across builds without shipping it in layers.
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -pl "${SERVICE}" -am package -DskipTests

# ------------------------------------------------------------------------------
FROM eclipse-temurin:21-jre-alpine AS runtime

ARG SERVICE
ARG SERVICE_PORT=8080

LABEL org.opencontainers.image.title="fintech-${SERVICE}" \
      org.opencontainers.image.description="FinTech Risk Platform microservice (${SERVICE})" \
      org.opencontainers.image.source="https://github.com/Oubay-S/fintech-mlops-platform" \
      org.opencontainers.image.licenses="Academic"

# Dedicated non-root user (UID 1001, matches the Kubernetes securityContext).
RUN addgroup -g 1001 -S app && adduser -S -u 1001 -G app app

WORKDIR /app

COPY --from=builder --chown=1001:1001 /build/${SERVICE}/target/*.jar app.jar

USER 1001

# Container-aware JVM tuning; `ExitOnOutOfMemoryError` lets Kubernetes restart
# a pod instead of leaving it in a broken state.
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseG1GC -XX:+ExitOnOutOfMemoryError" \
    LANG=C.UTF-8

EXPOSE ${SERVICE_PORT}

# `exec` is mandatory: it makes the JVM PID 1 so SIGTERM reaches Spring Boot's
# graceful shutdown (server.shutdown=graceful) instead of being swallowed by sh.
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
