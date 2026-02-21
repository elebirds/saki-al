package agent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"testing"
)

type fakeUploader struct {
	objectKey   string
	contentType string
	size        int64
	payload     []byte
}

func (f *fakeUploader) Upload(
	_ context.Context,
	objectKey string,
	reader io.Reader,
	size int64,
	contentType string,
) (etag string, err error) {
	data, err := io.ReadAll(reader)
	if err != nil {
		return "", err
	}
	f.objectKey = objectKey
	f.contentType = contentType
	f.size = size
	f.payload = data
	return "etag-test", nil
}

func TestValidateKernelEnvRejectsCredentials(t *testing.T) {
	a := NewWithUploader(Config{RunDir: t.TempDir(), MinIOBucket: "bucket"}, &fakeUploader{})
	if err := a.ValidateKernelEnv(map[string]string{"MINIO_ACCESS_KEY": "x"}); err == nil {
		t.Fatalf("expected forbidden env error")
	}
	if err := a.ValidateKernelEnv(map[string]string{"SAFE_KEY": "x"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestUploadArtifactStreamsByAgent(t *testing.T) {
	workspace := t.TempDir()
	filePath := filepath.Join(workspace, "output", "best.pt")
	if err := os.MkdirAll(filepath.Dir(filePath), 0o755); err != nil {
		t.Fatalf("mkdir failed: %v", err)
	}
	content := []byte("model-bytes")
	if err := os.WriteFile(filePath, content, 0o644); err != nil {
		t.Fatalf("write file failed: %v", err)
	}
	sum := sha256.Sum256(content)
	checksum := hex.EncodeToString(sum[:])

	uploader := &fakeUploader{}
	a := NewWithUploader(Config{
		RunDir:      t.TempDir(),
		MinIOBucket: "runtime-bucket",
		MinIOPrefix: "runtime-artifacts",
	}, uploader)

	storageURI, etag, err := a.UploadArtifact(context.Background(), ArtifactMeta{
		KernelInstanceID: "kernel-1",
		StepID:           "step-1",
		WorkspaceRoot:    workspace,
		RelativePath:     "output/best.pt",
		Kind:             "model",
		Required:         true,
		SizeBytes:        int64(len(content)),
		SHA256:           checksum,
	})
	if err != nil {
		t.Fatalf("upload artifact failed: %v", err)
	}
	if etag != "etag-test" {
		t.Fatalf("unexpected etag: %s", etag)
	}
	if storageURI != "s3://runtime-bucket/runtime-artifacts/kernel-1/step-1/output/best.pt" {
		t.Fatalf("unexpected storage uri: %s", storageURI)
	}
	if uploader.objectKey != "runtime-artifacts/kernel-1/step-1/output/best.pt" {
		t.Fatalf("unexpected object key: %s", uploader.objectKey)
	}
	if uploader.size != int64(len(content)) {
		t.Fatalf("unexpected size: %d", uploader.size)
	}
	if string(uploader.payload) != string(content) {
		t.Fatalf("payload mismatch")
	}
}

func TestUploadArtifactRejectsPathTraversal(t *testing.T) {
	uploader := &fakeUploader{}
	a := NewWithUploader(Config{
		RunDir:      t.TempDir(),
		MinIOBucket: "runtime-bucket",
	}, uploader)

	_, _, err := a.UploadArtifact(context.Background(), ArtifactMeta{
		KernelInstanceID: "kernel-1",
		StepID:           "step-1",
		WorkspaceRoot:    t.TempDir(),
		RelativePath:     "../secrets.txt",
	})
	if err == nil {
		t.Fatalf("expected path traversal error")
	}
}

func TestListKernelInstanceAndKill(t *testing.T) {
	runDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(runDir, "k1.ctl.sock"), []byte{}, 0o644); err != nil {
		t.Fatalf("write socket file failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "k1.evt.sock"), []byte{}, 0o644); err != nil {
		t.Fatalf("write socket file failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "k2.ctl.sock"), []byte{}, 0o644); err != nil {
		t.Fatalf("write socket file failed: %v", err)
	}

	a := NewWithUploader(Config{
		RunDir:      runDir,
		CacheDir:    t.TempDir(),
		MinIOBucket: "runtime-bucket",
	}, &fakeUploader{})

	ids, err := a.ListKernelInstanceIDs()
	if err != nil {
		t.Fatalf("list kernels failed: %v", err)
	}
	if len(ids) != 2 {
		t.Fatalf("expected 2 kernel ids, got %d", len(ids))
	}

	socketCount, err := a.SocketCount()
	if err != nil {
		t.Fatalf("socket count failed: %v", err)
	}
	if socketCount != 3 {
		t.Fatalf("expected 3 sockets, got %d", socketCount)
	}

	if err := a.KillKernel("k1"); err != nil {
		t.Fatalf("kill kernel failed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(runDir, "k1.ctl.sock")); !os.IsNotExist(err) {
		t.Fatalf("expected k1.ctl.sock removed")
	}
	if _, err := os.Stat(filepath.Join(runDir, "k1.evt.sock")); !os.IsNotExist(err) {
		t.Fatalf("expected k1.evt.sock removed")
	}
}
