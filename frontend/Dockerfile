
FROM node:26-slim

WORKDIR /app

# Copy package files first for better caching
COPY package.json package-lock.json* ./
RUN npm install

# Copy the rest of the app
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
