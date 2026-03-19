package runtime

import "log/slog"

func deliveryRoleLoop(parts assembly, logger *slog.Logger) loopRunner {
	if !parts.roles.Has(RuntimeRoleDelivery) {
		return nil
	}

	return newPollingLoop(pollingLoopConfig{
		name:     "outbox-worker",
		interval: durationOrDefault(parts.outboxInterval, defaultOutboxInterval),
		runOnce:  outboxRunOnceFunc(parts.outboxWorker),
		logger:   logger,
	})
}
