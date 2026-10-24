# Stage 1: build the app
FROM node:26-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Call the API on the same origin; nginx forwards /api to the backend
ENV VITE_API_URL=/
RUN npm run build

# Stage 2: serve it with nginx as a non-root user, on port 8080
FROM nginxinc/nginx-unprivileged:alpine

COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --chown=nginx:nginx security-headers.conf /etc/nginx/security-headers.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
