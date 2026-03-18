package storage

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type minioProvider struct {
	client *minio.Client
	bucket string
}

func NewMinIOProvider(cfg Config) (Provider, error) {
	if strings.TrimSpace(cfg.Endpoint) == "" {
		return nil, &Error{Op: "new", Err: errors.New("missing minio endpoint")}
	}
	if strings.TrimSpace(cfg.AccessKey) == "" {
		return nil, &Error{Op: "new", Err: errors.New("missing minio access key")}
	}
	if strings.TrimSpace(cfg.SecretKey) == "" {
		return nil, &Error{Op: "new", Err: errors.New("missing minio secret key")}
	}
	if strings.TrimSpace(cfg.Bucket) == "" {
		return nil, &Error{Op: "new", Err: errors.New("missing minio bucket name")}
	}

	endpoint, secure := normalizeEndpoint(cfg.Endpoint, cfg.Secure)
	client, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(cfg.AccessKey, cfg.SecretKey, ""),
		Secure: secure,
		Region: "us-east-1",
	})
	if err != nil {
		return nil, &Error{Op: "new", Err: errProviderBackend}
	}

	return &minioProvider{
		client: client,
		bucket: cfg.Bucket,
	}, nil
}

func (p *minioProvider) Bucket() string {
	return p.bucket
}

func (p *minioProvider) SignPutObject(ctx context.Context, objectKey string, expiry time.Duration, contentType string) (string, error) {
	headers := make(http.Header)
	if contentType != "" {
		headers.Set("Content-Type", contentType)
	}

	signedURL, err := p.client.PresignHeader(ctx, "PUT", p.bucket, objectKey, expiry, nil, headers)
	if err != nil {
		return "", wrapMinIOError("sign-put", objectKey, err)
	}
	return signedURL.String(), nil
}

func (p *minioProvider) SignGetObject(ctx context.Context, objectKey string, expiry time.Duration) (string, error) {
	signedURL, err := p.client.PresignedGetObject(ctx, p.bucket, objectKey, expiry, nil)
	if err != nil {
		return "", wrapMinIOError("sign-get", objectKey, err)
	}
	return signedURL.String(), nil
}

func (p *minioProvider) StatObject(ctx context.Context, objectKey string) (*ObjectStat, error) {
	info, err := p.client.StatObject(ctx, p.bucket, objectKey, minio.StatObjectOptions{})
	if err != nil {
		return nil, wrapMinIOError("stat", objectKey, err)
	}

	return &ObjectStat{
		Size:         info.Size,
		ETag:         info.ETag,
		ContentType:  info.ContentType,
		LastModified: info.LastModified,
	}, nil
}

func (p *minioProvider) DownloadObject(ctx context.Context, objectKey string, dst string) error {
	obj, err := p.client.GetObject(ctx, p.bucket, objectKey, minio.GetObjectOptions{})
	if err != nil {
		return wrapMinIOError("download", objectKey, err)
	}
	defer obj.Close()

	if _, err := obj.Stat(); err != nil {
		return wrapMinIOError("download", objectKey, err)
	}

	tmpFile, err := os.CreateTemp(filepath.Dir(dst), filepath.Base(dst)+".tmp-*")
	if err != nil {
		return &Error{Op: "download", Key: objectKey, Err: err}
	}
	tmpPath := tmpFile.Name()
	success := false
	defer func() {
		_ = tmpFile.Close()
		if !success {
			_ = os.Remove(tmpPath)
		}
	}()

	if _, err := io.Copy(tmpFile, obj); err != nil {
		return wrapMinIOError("download", objectKey, err)
	}
	if err := tmpFile.Close(); err != nil {
		return &Error{Op: "download", Key: objectKey, Err: err}
	}
	if err := os.Rename(tmpPath, dst); err != nil {
		return &Error{Op: "download", Key: objectKey, Err: err}
	}
	success = true
	return nil
}

func normalizeEndpoint(raw string, secure bool) (string, bool) {
	trimmed := strings.TrimSpace(raw)
	if !strings.Contains(trimmed, "://") {
		return trimmed, secure
	}

	parsed, err := url.Parse(trimmed)
	if err != nil {
		return trimmed, secure
	}
	if parsed.Host == "" {
		return trimmed, secure
	}
	return parsed.Host, parsed.Scheme == "https"
}

func wrapMinIOError(op string, objectKey string, err error) error {
	if err == nil {
		return nil
	}

	resp := minio.ToErrorResponse(err)
	if resp.Code == "NoSuchKey" || resp.Code == "NoSuchObject" || resp.Code == "NotFound" {
		return &Error{Op: op, Key: objectKey, Err: ErrObjectNotFound}
	}
	return &Error{Op: op, Key: objectKey, Err: errProviderBackend}
}
