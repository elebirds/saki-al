package runtime

import (
	"log/slog"
)

func schedulerRoleLoop(parts assembly, logger *slog.Logger) loopRunner {
	if !parts.roles.Has(RuntimeRoleScheduler) {
		return nil
	}

	return newPollingLoop(pollingLoopConfig{
		name:     "scheduler",
		interval: durationOrDefault(parts.schedulerInterval, defaultSchedulerInterval),
		runOnce:  schedulerTickFunc(parts.schedulerTicker),
		logger:   logger,
	})
}
