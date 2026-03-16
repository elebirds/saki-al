package observe

import "context"

func SetupOTel(_ context.Context, _ string) (func(context.Context) error, error) {
	return func(context.Context) error {
		return nil
	}, nil
}
