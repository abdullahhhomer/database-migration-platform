FROM python:3.12-slim

WORKDIR /app

COPY generator.py .

RUN pip install --no-cache-dir psycopg2-binary

CMD ["python", "generator.py"]