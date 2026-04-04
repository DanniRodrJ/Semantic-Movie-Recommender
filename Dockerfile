FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y gcc libpq-dev \
    && apt-get clean

COPY requirements.txt /app/
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY streaming_service/ /app/
RUN python manage.py collectstatic --noinput

EXPOSE 8050

CMD ["uvicorn", "streaming_service.asgi:application", "--host", "0.0.0.0", "--port", "8050"]
