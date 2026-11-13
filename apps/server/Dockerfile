FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8000

CMD ["sh", "-c", "exec daphne -b 0.0.0.0 -p \"${PORT:-8000}\" core.asgi:application"]
