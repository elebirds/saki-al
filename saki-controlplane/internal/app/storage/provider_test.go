package storage

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/minio/minio-go/v7"
)

func TestMinioProviderSignsPutAndGetURL(t *testing.T) {
	t.Parallel()

	p, err := NewMinIOProvider(Config{
		Endpoint:  "127.0.0.1:9000",
		AccessKey: "access-key",
		SecretKey: "secret-key",
		Bucket:    "assets",
		Secure:    false,
	})
	if err != nil {
		t.Fatalf("new minio provider: %v", err)
	}

	putURL, err := p.SignPutObject(context.Background(), "project/asset.png", 5*time.Minute, "image/png")
	if err != nil {
		t.Fatalf("sign put object: %v", err)
	}

	getURL, err := p.SignGetObject(context.Background(), "project/asset.png", 5*time.Minute)
	if err != nil {
		t.Fatalf("sign get object: %v", err)
	}

	assertSignedURL(t, putURL, "/assets/project/asset.png")
	assertSignedURL(t, getURL, "/assets/project/asset.png")
}

func TestMinioProviderStatsAndDownloadsObject(t *testing.T) {
	t.Parallel()

	const objectKey = "project/asset.png"
	const objectBody = "hello-object-storage"
	const objectETag = "deadbeef"

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		expectedPath := "/assets/" + objectKey
		if r.URL.Path != expectedPath {
			http.NotFound(w, r)
			return
		}

		switch r.Method {
		case http.MethodHead:
			w.Header().Set("ETag", "\""+objectETag+"\"")
			w.Header().Set("Content-Length", "20")
			w.Header().Set("Content-Type", "image/png")
			w.Header().Set("Last-Modified", "Mon, 02 Jan 2006 15:04:05 GMT")
			w.WriteHeader(http.StatusOK)
		case http.MethodGet:
			w.Header().Set("ETag", "\""+objectETag+"\"")
			w.Header().Set("Content-Length", "20")
			w.Header().Set("Content-Type", "image/png")
			w.Header().Set("Last-Modified", "Mon, 02 Jan 2006 15:04:05 GMT")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(objectBody))
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}))
	defer server.Close()

	endpoint := strings.TrimPrefix(server.URL, "http://")
	p, err := NewMinIOProvider(Config{
		Endpoint:  endpoint,
		AccessKey: "access-key",
		SecretKey: "secret-key",
		Bucket:    "assets",
		Secure:    false,
	})
	if err != nil {
		t.Fatalf("new minio provider: %v", err)
	}

	stat, err := p.StatObject(context.Background(), objectKey)
	if err != nil {
		t.Fatalf("stat object: %v", err)
	}
	if stat.Size != 20 {
		t.Fatalf("unexpected size: %d", stat.Size)
	}
	if stat.ETag != objectETag {
		t.Fatalf("unexpected etag: %q", stat.ETag)
	}
	if stat.ContentType != "image/png" {
		t.Fatalf("unexpected content type: %q", stat.ContentType)
	}
	if stat.LastModified.IsZero() {
		t.Fatal("expected last modified to be set")
	}

	dst := filepath.Join(t.TempDir(), "download.bin")
	if err := p.DownloadObject(context.Background(), objectKey, dst); err != nil {
		t.Fatalf("download object: %v", err)
	}

	data, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("read downloaded object: %v", err)
	}
	if string(data) != objectBody {
		t.Fatalf("unexpected downloaded body: %q", string(data))
	}
}

func TestProviderErrorDoesNotExposeMinIOErrorType(t *testing.T) {
	t.Parallel()

	notFoundErr := wrapMinIOError("download", "project/asset.png", minio.ErrorResponse{Code: "NoSuchKey"})
	if !errors.Is(notFoundErr, ErrObjectNotFound) {
		t.Fatalf("expected errors.Is(err, ErrObjectNotFound) to be true, got err=%v", notFoundErr)
	}
	var minioErr minio.ErrorResponse
	if errors.As(notFoundErr, &minioErr) {
		t.Fatalf("expected provider error not to expose minio error type, got %+v", minioErr)
	}

	otherErr := wrapMinIOError("download", "project/asset.png", minio.ErrorResponse{Code: "AccessDenied"})
	if errors.Is(otherErr, ErrObjectNotFound) {
		t.Fatalf("expected errors.Is(err, ErrObjectNotFound) to be false, got err=%v", otherErr)
	}
	if errors.As(otherErr, &minioErr) {
		t.Fatalf("expected provider error not to expose minio error type for non-notfound error, got %+v", minioErr)
	}
}

func TestMinioProviderDownloadObjectDoesNotCreateFileOnRemoteError(t *testing.T) {
	t.Parallel()

	const objectKey = "project/missing.bin"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	endpoint := strings.TrimPrefix(server.URL, "http://")
	p, err := NewMinIOProvider(Config{
		Endpoint:  endpoint,
		AccessKey: "access-key",
		SecretKey: "secret-key",
		Bucket:    "assets",
		Secure:    false,
	})
	if err != nil {
		t.Fatalf("new minio provider: %v", err)
	}

	dst := filepath.Join(t.TempDir(), "missing.bin")
	if err := p.DownloadObject(context.Background(), objectKey, dst); err == nil {
		t.Fatal("expected download object to fail for missing remote object")
	}
	if _, err := os.Stat(dst); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expected destination file to not exist after failed download, got err=%v", err)
	}
}

func TestNewMinIOProviderDoesNotExposeBackendInitError(t *testing.T) {
	t.Parallel()

	_, err := NewMinIOProvider(Config{
		Endpoint:  "http://[::1",
		AccessKey: "access-key",
		SecretKey: "secret-key",
		Bucket:    "assets",
		Secure:    false,
	})
	if err == nil {
		t.Fatal("expected new minio provider to fail with invalid endpoint")
	}
	if !errors.Is(err, errProviderBackend) {
		t.Fatalf("expected errors.Is(err, errProviderBackend) to be true, got err=%v", err)
	}
	var urlErr *url.Error
	if errors.As(err, &urlErr) {
		t.Fatalf("expected provider init error not to expose backend error type, got %+v", urlErr)
	}
}

func assertSignedURL(t *testing.T, rawURL string, expectedPath string) {
	t.Helper()

	parsed, err := url.Parse(rawURL)
	if err != nil {
		t.Fatalf("parse signed url: %v", err)
	}
	if parsed.Path != expectedPath {
		t.Fatalf("unexpected path: %q", parsed.Path)
	}
	query := parsed.Query()
	if query.Get("X-Amz-Algorithm") == "" {
		t.Fatalf("expected X-Amz-Algorithm in signed URL: %q", rawURL)
	}
	if query.Get("X-Amz-Signature") == "" {
		t.Fatalf("expected X-Amz-Signature in signed URL: %q", rawURL)
	}
	if query.Get("X-Amz-Credential") == "" {
		t.Fatalf("expected X-Amz-Credential in signed URL: %q", rawURL)
	}
}
