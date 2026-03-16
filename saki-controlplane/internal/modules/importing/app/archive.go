package app

import (
	"archive/zip"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func resolveImportSourcePath(formatProfile, objectKey string) (string, func(), error) {
	if !strings.HasSuffix(strings.ToLower(objectKey), ".zip") {
		return objectKey, func() {}, nil
	}

	root, err := os.MkdirTemp("", "saki-import-*")
	if err != nil {
		return "", nil, fmt.Errorf("create import temp dir: %w", err)
	}
	cleanup := func() {
		_ = os.RemoveAll(root)
	}

	if err := extractZipArchive(objectKey, root); err != nil {
		cleanup()
		return "", nil, err
	}

	switch strings.ToLower(formatProfile) {
	case "coco":
		path, err := findCOCOAnnotationsPath(root)
		if err != nil {
			cleanup()
			return "", nil, err
		}
		return path, cleanup, nil
	default:
		return root, cleanup, nil
	}
}

func extractZipArchive(zipPath string, targetRoot string) error {
	reader, err := zip.OpenReader(zipPath)
	if err != nil {
		return fmt.Errorf("open import archive: %w", err)
	}
	defer reader.Close()

	cleanRoot := filepath.Clean(targetRoot)
	for _, file := range reader.File {
		targetPath := filepath.Join(cleanRoot, file.Name)
		cleanTarget := filepath.Clean(targetPath)
		if cleanTarget != cleanRoot && !strings.HasPrefix(cleanTarget, cleanRoot+string(os.PathSeparator)) {
			return fmt.Errorf("zip entry escapes target root: %s", file.Name)
		}

		if file.FileInfo().IsDir() {
			if err := os.MkdirAll(cleanTarget, 0o755); err != nil {
				return fmt.Errorf("create extracted dir: %w", err)
			}
			continue
		}

		if err := os.MkdirAll(filepath.Dir(cleanTarget), 0o755); err != nil {
			return fmt.Errorf("create extracted parent dir: %w", err)
		}
		src, err := file.Open()
		if err != nil {
			return fmt.Errorf("open zip entry: %w", err)
		}

		dst, err := os.OpenFile(cleanTarget, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, file.Mode())
		if err != nil {
			_ = src.Close()
			return fmt.Errorf("create extracted file: %w", err)
		}

		_, copyErr := io.Copy(dst, src)
		closeErr := dst.Close()
		srcErr := src.Close()
		if copyErr != nil {
			return fmt.Errorf("extract zip entry: %w", copyErr)
		}
		if closeErr != nil {
			return fmt.Errorf("close extracted file: %w", closeErr)
		}
		if srcErr != nil {
			return fmt.Errorf("close zip entry: %w", srcErr)
		}
	}

	return nil
}

func findCOCOAnnotationsPath(root string) (string, error) {
	candidates := make([]string, 0, 4)
	preferred := make([]string, 0, 2)
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		if !strings.EqualFold(filepath.Ext(path), ".json") {
			return nil
		}
		candidates = append(candidates, path)
		base := strings.ToLower(filepath.Base(path))
		if base == "annotations.json" || strings.HasPrefix(base, "instances") {
			preferred = append(preferred, path)
		}
		return nil
	})
	if err != nil {
		return "", fmt.Errorf("scan coco annotations: %w", err)
	}
	switch {
	case len(preferred) == 1:
		return preferred[0], nil
	case len(candidates) == 1:
		return candidates[0], nil
	case len(candidates) == 0:
		return "", fmt.Errorf("no coco annotations json found in archive")
	default:
		return "", fmt.Errorf("multiple coco annotations json files found in archive")
	}
}
