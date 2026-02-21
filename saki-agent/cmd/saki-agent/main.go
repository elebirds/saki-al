package main

import (
	"context"
	"flag"
	"log"
	"os/signal"
	"syscall"

	"github.com/elebirds/saki/saki-agent/internal/agent"
)

func main() {
	var runDir string
	var minioEndpoint string
	var minioAccessKey string
	var minioSecretKey string
	var minioBucket string
	var minioPrefix string
	var minioUseSSL bool
	flag.StringVar(&runDir, "run-dir", "/var/run/saki-agent", "runtime socket directory")
	flag.StringVar(&minioEndpoint, "minio-endpoint", "", "minio endpoint host:port")
	flag.StringVar(&minioAccessKey, "minio-access-key", "", "minio access key")
	flag.StringVar(&minioSecretKey, "minio-secret-key", "", "minio secret key")
	flag.StringVar(&minioBucket, "minio-bucket", "", "minio bucket name")
	flag.StringVar(&minioPrefix, "minio-prefix", "runtime-artifacts", "artifact object key prefix")
	flag.BoolVar(&minioUseSSL, "minio-ssl", false, "use https to connect minio")
	flag.Parse()

	daemon, err := agent.New(agent.Config{
		RunDir:         runDir,
		MinIOEndpoint:  minioEndpoint,
		MinIOAccessKey: minioAccessKey,
		MinIOSecretKey: minioSecretKey,
		MinIOBucket:    minioBucket,
		MinIOPrefix:    minioPrefix,
		MinIOUseSSL:    minioUseSSL,
	})
	if err != nil {
		log.Fatalf("init agent failed: %v", err)
	}
	if err := daemon.PrepareRunDir(); err != nil {
		log.Fatalf("prepare run dir failed: %v", err)
	}
	if err := daemon.CleanupStaleSockets(); err != nil {
		log.Fatalf("cleanup stale sockets failed: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	<-ctx.Done()
}
