FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements/bot.txt requirements/bot.txt
RUN pip install -r requirements/bot.txt
COPY bot/ bot/
CMD ["python", "-m", "bot"]
