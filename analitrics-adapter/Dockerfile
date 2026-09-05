FROM node:22-bookworm-slim

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY tsconfig.json ./
COPY src ./src

RUN npm run build \
  && NODE_ENV=test node --test dist/uploadFileWrapperServer.test.js

ENV NODE_ENV=production

EXPOSE 3096

CMD ["npm", "run", "start:upload-file-wrapper"]
