# Multi-stage build: compile Go binary, then copy into minimal runtime image

# ── Build stage ──
FROM golang:1.24-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /sbom-tree ./cmd/

# ── Runtime stage ──
FROM alpine:3.20

RUN apk add --no-cache ca-certificates

COPY --from=builder /sbom-tree /usr/local/bin/sbom-tree

ENTRYPOINT ["sbom-tree"]
