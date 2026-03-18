package storage

import (
	"context"
	"errors"
	"time"
)

var ErrObjectNotFound = errors.New("object not found")
var errProviderBackend = errors.New("provider backend error")

type ObjectStat struct {
	Size         int64
	ETag         string
	ContentType  string
	LastModified time.Time
}

type Provider interface {
	Bucket() string
	SignPutObject(ctx context.Context, objectKey string, expiry time.Duration, contentType string) (string, error)
	SignGetObject(ctx context.Context, objectKey string, expiry time.Duration) (string, error)
	StatObject(ctx context.Context, objectKey string) (*ObjectStat, error)
	DownloadObject(ctx context.Context, objectKey string, dst string) error
}

type Config struct {
	Endpoint  string
	AccessKey string
	SecretKey string
	Bucket    string
	Secure    bool
}

type Error struct {
	Op  string
	Key string
	Err error
}

func (e *Error) Error() string {
	if e == nil {
		return "storage provider error"
	}
	if e.Key == "" {
		return "storage provider " + e.Op + " failed"
	}
	return "storage provider " + e.Op + " failed for object " + e.Key
}

func (e *Error) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Err
}
