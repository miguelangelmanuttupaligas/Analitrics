FROM node:22-bookworm-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
COPY prompts ./prompts

RUN npm run build

ENV NODE_ENV=production

EXPOSE 3095

CMD ["npm", "start"]
