FROM node:24-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src ./src
COPY server ./server
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["node", "server/main.js"]
