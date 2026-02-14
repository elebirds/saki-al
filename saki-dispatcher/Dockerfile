FROM golang:1.24-alpine AS builder

WORKDIR /app

RUN apk add --no-cache ca-certificates git

COPY go.mod ./
COPY go.sum ./
RUN go mod download

COPY cmd ./cmd
COPY internal ./internal

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /bin/saki-dispatcher ./cmd/dispatcher

FROM alpine:3.22

RUN apk add --no-cache ca-certificates

WORKDIR /app

COPY --from=builder /bin/saki-dispatcher /usr/local/bin/saki-dispatcher
COPY db/migrations ./db/migrations

EXPOSE 50051 50052

ENTRYPOINT ["saki-dispatcher"]
