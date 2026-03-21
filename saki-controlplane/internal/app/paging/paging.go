package paging

// Normalize 统一控制 public API 列表查询的分页边界，避免各模块各自维护默认值和上限。
func Normalize(page int, limit int) (int, int, int) {
	if page <= 0 {
		page = 1
	}
	if limit <= 0 {
		limit = 20
	}
	if limit > 200 {
		limit = 200
	}
	return page, limit, (page - 1) * limit
}
