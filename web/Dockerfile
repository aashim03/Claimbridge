FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# The lockfile is produced on Windows; let npm resolve the Linux-only optional packages here.
RUN npm install --no-audit --no-fund
COPY . .
# Rewrites are resolved at build time: /api/* is proxied to the API service.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
