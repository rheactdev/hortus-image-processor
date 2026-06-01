FROM node:22-slim

# Install ImageMagick
RUN apt-get update && apt-get install -y imagemagick && rm -rf /var/lib/apt/lists/*

# Fix ImageMagick security policy to allow PSD reading/writing if restricted
RUN sed -i 's/<policy domain="coder" rights="none" pattern="PSD" \/>/<policy domain="coder" rights="read|write" pattern="PSD" \/>/g' /etc/ImageMagick-6/policy.xml || true

WORKDIR /app

# Enable pnpm
RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install

COPY tsconfig.json ./
COPY src ./src

# Start the server using tsx
CMD ["pnpm", "tsx", "src/index.ts"]
