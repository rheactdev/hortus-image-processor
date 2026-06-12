# Office converter

Small authenticated HTTP service that converts Word, Excel, and PowerPoint
documents to PDF with headless LibreOffice.

## Deploy

1. Copy this directory from the `hortus-backend` repository to the Hetzner host.
2. Copy `.env.example` to `.env` and set a long random
   `OFFICE_CONVERTER_SECRET`.
3. Run `docker compose up -d --build`.
4. Put an HTTPS reverse proxy in front of `127.0.0.1:8080`.
5. Set the same secret and the public HTTPS URL in the Hortus web deployment:
   `OFFICE_CONVERTER_URL` and `OFFICE_CONVERTER_SECRET`.

The service accepts only HTTPS signed source/destination URLs, limits source
documents to 100 MiB by default, and processes at most two conversions at once.
