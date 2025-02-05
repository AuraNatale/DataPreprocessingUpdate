FROM python:3.10


ENV POETRY_VERSION=1.8.4
ENV POETRY_HOME=/opt/poetry
# Poetry cache directory: it should be accessible by non-root users
ENV POETRY_CACHE_DIR="/data_preprocessing/.cache/pypoetry"
ENV POETRY_VIRTUALENVS_CREATE=false
ENV PYTHONPATH=/data_preprocessing/src

RUN pip install --upgrade pip

# Install Poetry
RUN pip install poetry==${POETRY_VERSION}


# Create a non-root user for security reasons (trivy - DS002)
RUN groupadd -r appgroup && useradd -r -g appgroup DataProcessingAdmin

# Create the application directory
RUN mkdir -p /data_preprocessing/.cache/pypoetry && \
    chown -R DataProcessingAdmin:appgroup /data_preprocessing

# Imposta la directory di lavoro nel container.
WORKDIR /data_preprocessing

COPY poetry.lock pyproject.toml /data_preprocessing/

# Install dependencies
RUN poetry install

COPY src/  /data_preprocessing/src
COPY data/ /data_preprocessing/data

# Expose port 8003
EXPOSE 8003


RUN echo "DataProcessingAdmin:password" | chpasswd

# Run the application
CMD ["poetry", "run", "start"]

# Periodic healthcheck to ensure the container is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8003/health || exit 1

