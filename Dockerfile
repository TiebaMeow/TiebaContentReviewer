FROM python:3.14-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project definition files
COPY pyproject.toml README.md ./

# Copy source code
COPY src/ src/
COPY main.py .

# Install dependencies and the project itself into the system python
# --system avoids creating a virtual environment inside the container
RUN uv pip install --system .

# Run the application
CMD ["python", "main.py"]
