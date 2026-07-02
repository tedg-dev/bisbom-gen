# Multi-stage build: compile Go binary, then copy into minimal runtime image

# ── Build stage ──
FROM golang:1.22-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /spdx-indexing ./cmd/

# ── Runtime stage ──
FROM alpine:3.20

RUN apk add --no-cache ca-certificates

COPY --from=builder /spdx-indexing /usr/local/bin/spdx-indexing

ENTRYPOINT ["spdx-indexing"]
