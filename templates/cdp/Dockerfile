# Multi-stage build: small final image, fast cold start.
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev

FROM node:22-slim AS builder
WORKDIR /app
COPY package.json ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
# Run as a non-root user
RUN useradd -m -u 1001 agent && chown -R agent:agent /app
USER agent

COPY --from=deps     /app/node_modules ./node_modules
COPY --from=builder  /app/dist          ./dist
COPY package.json ./

# Default to server mode in containers — CLI REPL doesn't make sense in a daemon.
ENV MODE=server
ENV NODE_ENV=production

EXPOSE 8080
CMD ["node", "dist/index.js"]
