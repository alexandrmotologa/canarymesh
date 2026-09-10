FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

FROM python:3.12-slim AS runner

WORKDIR /app

# Install runtime dependencies and copy virtual env / packages
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/canarymesh /usr/local/bin/canarymesh
COPY scenarios/ ./scenarios/

# Create non-root user
RUN useradd -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080 8090

ENTRYPOINT ["canarymesh"]
CMD ["start", "--proxy-host", "0.0.0.0", "--proxy-port", "8080", "--control-host", "0.0.0.0", "--control-port", "8090"]
