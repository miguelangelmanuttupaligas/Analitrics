FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "scripts/nl_sql_file.py"]
