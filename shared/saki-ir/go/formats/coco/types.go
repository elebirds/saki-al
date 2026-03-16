package coco

type ParseRequest struct {
	AnnotationsPath string
}

type document struct {
	Categories  []category   `json:"categories"`
	Images      []image      `json:"images"`
	Annotations []annotation `json:"annotations"`
}

type category struct {
	ID   any    `json:"id"`
	Name string `json:"name"`
}

type image struct {
	ID       any    `json:"id"`
	FileName string `json:"file_name"`
	Width    int32  `json:"width"`
	Height   int32  `json:"height"`
	CocoURL  string `json:"coco_url"`
}

type annotation struct {
	ID           any       `json:"id"`
	ImageID      any       `json:"image_id"`
	CategoryID   any       `json:"category_id"`
	BBox         []float32 `json:"bbox"`
	Segmentation any       `json:"segmentation"`
	Score        *float32  `json:"score"`
}
