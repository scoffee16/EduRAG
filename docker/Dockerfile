FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system edurage \
    && useradd --system --gid edurage --create-home --home-dir /home/edurage --shell /usr/sbin/nologin edurage

COPY pyproject.toml /app/pyproject.toml

# Install runtime dependencies before copying application sources so source-only
# changes do not invalidate the dependency layer.
RUN python -c "import pathlib, tomllib; project = tomllib.loads(pathlib.Path('/app/pyproject.toml').read_text(encoding='utf-8'))['project']; pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(project.get('dependencies', [])), encoding='utf-8')" \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir "Pillow>=10" "pytesseract>=0.3.13" \
    && rm /tmp/requirements.txt

COPY --chown=edurage:edurage src/ /app/src/

USER edurage

EXPOSE 8000

CMD ["uvicorn", "edurage.main:app", "--host", "0.0.0.0", "--port", "8000"]
