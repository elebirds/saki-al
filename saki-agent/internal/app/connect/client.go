package connect

type RuntimeClient struct {
	BaseURL string
}

func NewRuntimeClient(baseURL string) *RuntimeClient {
	return &RuntimeClient{BaseURL: baseURL}
}
