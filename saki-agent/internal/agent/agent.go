package agent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"mime"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/rs/zerolog"
)

var forbiddenKernelEnvPrefixes = []string{
	"MINIO_",
	"AWS_ACCESS_KEY_ID",
	"AWS_SECRET_ACCESS_KEY",
	"AWS_SESSION_TOKEN",
}

type Config struct {
	RunDir         string
	CacheDir       string
	MinIOEndpoint  string
	MinIOAccessKey string
	MinIOSecretKey string
	MinIOBucket    string
	MinIOPrefix    string
	MinIOUseSSL    bool
}

type KernelInstance struct {
	KernelInstanceID string
	ControlSocketURI string
	EventSocketURI   string
}

type ArtifactMeta struct {
	KernelInstanceID string
	StepID           string
	WorkspaceRoot    string
	RelativePath     string
	Kind             string
	Required         bool
	SizeBytes        int64
	SHA256           string
}

type artifactUploader interface {
	Upload(ctx context.Context, objectKey string, reader io.Reader, size int64, contentType string) (etag string, err error)
}

type minioUploader struct {
	client *minio.Client
	bucket string
}

type Agent struct {
	cfg      Config
	uploader artifactUploader
	logger   zerolog.Logger

	mu              sync.RWMutex
	draining        bool
	reconnectCount  int64
	lastReconnectAt time.Time
}

func New(cfg Config) (*Agent, error) {
	return NewWithLogger(cfg, zerolog.Nop())
}

func NewWithLogger(cfg Config, logger zerolog.Logger) (*Agent, error) {
	runDir := strings.TrimSpace(cfg.RunDir)
	if runDir == "" {
		runDir = "/var/run/saki-agent"
	}
	cacheDir := strings.TrimSpace(cfg.CacheDir)
	if cacheDir == "" {
		cacheDir = "/var/lib/saki-agent/cache"
	}
	cfg.RunDir = runDir
	cfg.CacheDir = cacheDir
	if shouldInitMinIO(cfg) {
		uploader, err := newMinIOUploader(cfg)
		if err != nil {
			return nil, err
		}
		return &Agent{cfg: cfg, uploader: uploader, logger: logger}, nil
	}
	return &Agent{cfg: cfg, logger: logger}, nil
}

func NewWithUploader(cfg Config, uploader artifactUploader) *Agent {
	runDir := strings.TrimSpace(cfg.RunDir)
	if runDir == "" {
		runDir = "/var/run/saki-agent"
	}
	cacheDir := strings.TrimSpace(cfg.CacheDir)
	if cacheDir == "" {
		cacheDir = "/var/lib/saki-agent/cache"
	}
	cfg.RunDir = runDir
	cfg.CacheDir = cacheDir
	return &Agent{cfg: cfg, uploader: uploader, logger: zerolog.Nop()}
}

func shouldInitMinIO(cfg Config) bool {
	return strings.TrimSpace(cfg.MinIOEndpoint) != "" ||
		strings.TrimSpace(cfg.MinIOAccessKey) != "" ||
		strings.TrimSpace(cfg.MinIOSecretKey) != "" ||
		strings.TrimSpace(cfg.MinIOBucket) != ""
}

func newMinIOUploader(cfg Config) (*minioUploader, error) {
	endpoint := strings.TrimSpace(cfg.MinIOEndpoint)
	accessKey := strings.TrimSpace(cfg.MinIOAccessKey)
	secretKey := strings.TrimSpace(cfg.MinIOSecretKey)
	bucket := strings.TrimSpace(cfg.MinIOBucket)
	if endpoint == "" || accessKey == "" || secretKey == "" || bucket == "" {
		return nil, fmt.Errorf("minio config incomplete: endpoint/access_key/secret_key/bucket are required")
	}
	client, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: cfg.MinIOUseSSL,
	})
	if err != nil {
		return nil, fmt.Errorf("init minio client: %w", err)
	}
	return &minioUploader{client: client, bucket: bucket}, nil
}

func (a *Agent) PrepareRunDir() error {
	if err := os.MkdirAll(a.cfg.RunDir, 0o700); err != nil {
		return fmt.Errorf("create run dir: %w", err)
	}
	if err := os.Chmod(a.cfg.RunDir, 0o700); err != nil {
		return fmt.Errorf("chmod run dir: %w", err)
	}
	return nil
}

func (a *Agent) PrepareCacheDir() error {
	if strings.TrimSpace(a.cfg.CacheDir) == "" {
		return nil
	}
	if err := os.MkdirAll(a.cfg.CacheDir, 0o755); err != nil {
		return fmt.Errorf("create cache dir: %w", err)
	}
	return nil
}

func (a *Agent) CleanupStaleSockets() error {
	pattern := filepath.Join(a.cfg.RunDir, "*.sock")
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return err
	}
	sort.Strings(matches)
	for _, socketPath := range matches {
		if err := os.Remove(socketPath); err != nil && !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("remove stale socket %s: %w", socketPath, err)
		}
	}
	return nil
}

func (a *Agent) SetDraining(draining bool) {
	a.mu.Lock()
	a.draining = draining
	a.mu.Unlock()
	a.logger.Info().Bool("draining", draining).Msg("agent drain 状态已更新")
}

func (a *Agent) IsDraining() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.draining
}

func (a *Agent) MarkReconnect() {
	a.mu.Lock()
	a.reconnectCount++
	a.lastReconnectAt = time.Now()
	count := a.reconnectCount
	last := a.lastReconnectAt
	a.mu.Unlock()
	a.logger.Info().Int64("reconnect_count", count).Time("last_reconnect_at", last).Msg("agent reconnect 已记录")
}

func (a *Agent) ReconnectSnapshot() (count int64, last time.Time) {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.reconnectCount, a.lastReconnectAt
}

func (a *Agent) RunDir() string {
	return a.cfg.RunDir
}

func (a *Agent) CacheDir() string {
	return a.cfg.CacheDir
}

func (a *Agent) KernelIPC(instanceID string) KernelInstance {
	safeID := strings.TrimSpace(instanceID)
	return KernelInstance{
		KernelInstanceID: safeID,
		ControlSocketURI: fmt.Sprintf("ipc://%s", filepath.Join(a.cfg.RunDir, safeID+".ctl.sock")),
		EventSocketURI:   fmt.Sprintf("ipc://%s", filepath.Join(a.cfg.RunDir, safeID+".evt.sock")),
	}
}

func (a *Agent) ValidateKernelEnv(env map[string]string) error {
	for key := range env {
		upper := strings.ToUpper(strings.TrimSpace(key))
		if upper == "" {
			continue
		}
		for _, prefix := range forbiddenKernelEnvPrefixes {
			if strings.HasPrefix(upper, prefix) {
				return fmt.Errorf("forbidden kernel env key: %s", key)
			}
		}
	}
	return nil
}

func (a *Agent) UploadArtifact(ctx context.Context, artifact ArtifactMeta) (storageURI string, etag string, err error) {
	if a.uploader == nil {
		return "", "", errors.New("artifact uploader not configured")
	}
	workspaceRoot := strings.TrimSpace(artifact.WorkspaceRoot)
	if workspaceRoot == "" {
		return "", "", fmt.Errorf("artifact workspace_root is required")
	}
	relativePath, err := cleanRelativePath(artifact.RelativePath)
	if err != nil {
		return "", "", err
	}
	localFile := filepath.Join(workspaceRoot, filepath.FromSlash(relativePath))
	file, err := os.Open(localFile)
	if err != nil {
		return "", "", fmt.Errorf("open artifact file: %w", err)
	}
	defer func() {
		_ = file.Close()
	}()
	stat, err := file.Stat()
	if err != nil {
		return "", "", fmt.Errorf("stat artifact file: %w", err)
	}
	if stat.IsDir() {
		return "", "", fmt.Errorf("artifact file path points to directory: %s", localFile)
	}
	if artifact.SizeBytes > 0 && artifact.SizeBytes != stat.Size() {
		return "", "", fmt.Errorf("artifact size mismatch expected=%d actual=%d", artifact.SizeBytes, stat.Size())
	}
	computedSHA, err := fileSHA256(file)
	if err != nil {
		return "", "", err
	}
	expectedSHA := strings.TrimSpace(artifact.SHA256)
	if expectedSHA != "" && !strings.EqualFold(expectedSHA, computedSHA) {
		return "", "", fmt.Errorf("artifact sha256 mismatch expected=%s actual=%s", expectedSHA, computedSHA)
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return "", "", fmt.Errorf("seek artifact file: %w", err)
	}

	objectKey := buildObjectKey(a.cfg, artifact, relativePath)
	contentType := mime.TypeByExtension(strings.ToLower(filepath.Ext(localFile)))
	if strings.TrimSpace(contentType) == "" {
		contentType = "application/octet-stream"
	}
	etag, err = a.uploader.Upload(ctx, objectKey, file, stat.Size(), contentType)
	if err != nil {
		return "", "", fmt.Errorf("upload artifact to minio: %w", err)
	}
	storageURI = fmt.Sprintf("s3://%s/%s", strings.TrimSpace(a.cfg.MinIOBucket), objectKey)
	return storageURI, etag, nil
}

func buildObjectKey(cfg Config, artifact ArtifactMeta, relativePath string) string {
	segments := []string{
		strings.Trim(strings.TrimSpace(cfg.MinIOPrefix), "/"),
		strings.Trim(strings.TrimSpace(artifact.KernelInstanceID), "/"),
		strings.Trim(strings.TrimSpace(artifact.StepID), "/"),
		strings.Trim(strings.TrimSpace(relativePath), "/"),
	}
	normalized := make([]string, 0, len(segments))
	for _, segment := range segments {
		if segment == "" {
			continue
		}
		normalized = append(normalized, segment)
	}
	return path.Join(normalized...)
}

func cleanRelativePath(raw string) (string, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "", fmt.Errorf("artifact relative_path is required")
	}
	clean := filepath.Clean(trimmed)
	if filepath.IsAbs(clean) {
		return "", fmt.Errorf("artifact relative_path must be relative: %s", raw)
	}
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("artifact relative_path escapes workspace: %s", raw)
	}
	return filepath.ToSlash(clean), nil
}

func fileSHA256(file *os.File) (string, error) {
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return "", fmt.Errorf("seek artifact file: %w", err)
	}
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", fmt.Errorf("hash artifact file: %w", err)
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func (u *minioUploader) Upload(
	ctx context.Context,
	objectKey string,
	reader io.Reader,
	size int64,
	contentType string,
) (etag string, err error) {
	uploadInfo, err := u.client.PutObject(
		ctx,
		u.bucket,
		objectKey,
		reader,
		size,
		minio.PutObjectOptions{ContentType: contentType},
	)
	if err != nil {
		return "", err
	}
	return uploadInfo.ETag, nil
}
