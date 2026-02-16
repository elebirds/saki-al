package orchestrator

import (
	"context"
	"time"

	"github.com/rs/zerolog"

	"github.com/elebirds/saki/saki-dispatcher/internal/controlplane"
)

type Service struct {
	interval     time.Duration
	controlPlane *controlplane.Service
	logger       zerolog.Logger
}

func NewService(intervalSec int, controlPlane *controlplane.Service, logger zerolog.Logger) *Service {
	if intervalSec <= 0 {
		intervalSec = 3
	}
	return &Service{
		interval:     time.Duration(intervalSec) * time.Second,
		controlPlane: controlPlane,
		logger:       logger,
	}
}

func (s *Service) Run(ctx context.Context) {
	ticker := time.NewTicker(s.interval)
	defer ticker.Stop()

	s.logger.Info().Dur("interval", s.interval).Msg("orchestrator loop started")
	for {
		select {
		case <-ctx.Done():
			s.logger.Info().Msg("orchestrator loop stopped")
			return
		case <-ticker.C:
			if s.controlPlane == nil {
				continue
			}
			if err := s.controlPlane.Tick(ctx); err != nil {
				s.logger.Warn().Err(err).Msg("orchestrator tick failed")
			}
		}
	}
}
