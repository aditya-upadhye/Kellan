FROM node:22-alpine AS build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
COPY docs/schemas/ /app/docs/schemas/
RUN npm run build

FROM nginx:1.29-alpine

ENV API_UPSTREAM=http://api:8000 \
    API_UPSTREAM_HOST=api

COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80
