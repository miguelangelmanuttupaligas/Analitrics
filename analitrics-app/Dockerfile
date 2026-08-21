FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts ./scripts
COPY alembic.ini ./
COPY migrations ./migrations

ENV PYTHONUNBUFFERED=1
ENV PYTHONWARNINGS=ignore

ENTRYPOINT ["python"]
CMD ["scripts/nl_sql_file.py"]
