# libris-api (NestJS). docker build -t libris-api libris-api
FROM node:22-slim AS build
WORKDIR /app
# Mạng đi qua proxy có CA riêng: build với --secret id=ca_cert,src=<file CA>; không có thì bỏ qua
ENV NODE_EXTRA_CA_CERTS=/run/secrets/ca_cert
# npm 10 có lỗi arborist với lockfile của dự án -> dùng npm 11
RUN --mount=type=secret,id=ca_cert,required=false npm install -g npm@11 --no-audit --no-fund
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=ca_cert,required=false npm ci --no-audit --no-fund
COPY tsconfig.json tsconfig.build.json nest-cli.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-slim
ENV NODE_ENV=production PORT=4000
WORKDIR /app
COPY --from=build --chown=node:node /app/package.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
USER node
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD node -e "fetch('http://localhost:'+process.env.PORT+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "dist/main"]
