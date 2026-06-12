FROM python:3.12-slim-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-dejavu-core \
    fonts-liberation2 \
  && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 converter
WORKDIR /app
COPY server.py /app/server.py
RUN chown -R converter:converter /app

USER converter
ENV PORT=8080
EXPOSE 8080

CMD ["python", "/app/server.py"]
