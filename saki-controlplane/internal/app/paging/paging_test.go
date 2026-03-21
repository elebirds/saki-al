package paging

import "testing"

func TestNormalizeAppliesDefaultBounds(t *testing.T) {
	page, limit, offset := Normalize(0, 0)
	if page != 1 || limit != 20 || offset != 0 {
		t.Fatalf("Normalize(0, 0) = (%d, %d, %d), want (1, 20, 0)", page, limit, offset)
	}
}

func TestNormalizeCapsLimitAndCalculatesOffset(t *testing.T) {
	page, limit, offset := Normalize(3, 500)
	if page != 3 || limit != 200 || offset != 400 {
		t.Fatalf("Normalize(3, 500) = (%d, %d, %d), want (3, 200, 400)", page, limit, offset)
	}
}
