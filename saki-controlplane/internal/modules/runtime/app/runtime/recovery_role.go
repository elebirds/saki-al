package runtime

import (
	"context"
	"log/slog"
)

type noopRecoveryLoop struct{}

func (noopRecoveryLoop) Run(context.Context) error {
	return nil
}

func recoveryRoleLoop(parts assembly, _ *slog.Logger) loopRunner {
	if !parts.roles.Has(RuntimeRoleRecovery) {
		return nil
	}
	return newPollingLoop(pollingLoopConfig{
		name:     "recovery",
		interval: durationOrDefault(0, defaultRecoveryInterval),
		runOnce: func(context.Context) error {
			return nil
		},
		logger: nil,
	})
}
