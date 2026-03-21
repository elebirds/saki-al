package app

import "github.com/elebirds/saki/saki-controlplane/internal/app/paging"

func normalizePage(page int, limit int) (int, int, int) {
	return paging.Normalize(page, limit)
}
