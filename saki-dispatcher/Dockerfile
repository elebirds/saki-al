FROM golang:1.24-alpine AS builder

WORKDIR /app

RUN apk add --no-cache ca-certificates git

# 配置 Go 国内镜像源（适用于腾讯云等国内服务器）
ENV GOPROXY=https://goproxy.cn,direct \
    GO111MODULE=on

# 复制 proto 目录用于 gRPC 代码生成
COPY proto /tmp/proto
COPY saki-dispatcher/go.mod ./
COPY saki-dispatcher/go.sum ./
RUN go mod download

COPY saki-dispatcher/cmd ./cmd
COPY saki-dispatcher/internal ./internal

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /bin/saki-dispatcher ./cmd/dispatcher

FROM alpine:3.22

RUN apk add --no-cache ca-certificates

WORKDIR /app

# 复制 entrypoint 脚本
COPY saki-dispatcher/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY --from=builder /bin/saki-dispatcher /usr/local/bin/saki-dispatcher
COPY saki-dispatcher/db ./db

EXPOSE 50051 50052

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD ["saki-dispatcher"]
