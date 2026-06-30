FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY slack_bot/ ./slack_bot/

COPY slack_bot/embeddings/chroma_db/ ./slack_bot/embeddings/chroma_db/

EXPOSE 8080

CMD ["python", "-u", "-m", "slack_bot.bot"]
