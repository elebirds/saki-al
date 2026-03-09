package controlplane

import (
	"context"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

type dispatchLaneCandidate struct {
	TaskID        uuid.UUID
	LaneID        string
	PluginID      string
	DispatchClass string
	ReadyAt       time.Time
	IsReady       bool
}

func (s *Service) listDispatchLaneCandidates(ctx context.Context, limit int) ([]dispatchLaneCandidate, error) {
	rows, err := s.queries.ListDispatchLaneHeadCandidates(ctx, int32(max(1, limit)))
	if err != nil {
		return nil, err
	}
	candidates := make([]dispatchLaneCandidate, 0, len(rows))
	now := time.Now().UTC()
	seen := make(map[string]struct{}, len(rows))
	for _, row := range rows {
		laneID := strings.TrimSpace(row.LaneID)
		if laneID == "" {
			laneID = row.TaskID.String()
		}
		if _, exists := seen[laneID]; exists {
			continue
		}
		seen[laneID] = struct{}{}
		readyAt := time.Time{}
		if row.UpdatedAt.Valid {
			readyAt = row.UpdatedAt.Time.UTC()
		}
		if readyAt.IsZero() && row.CreatedAt.Valid {
			readyAt = row.CreatedAt.Time.UTC()
		}
		candidates = append(candidates, dispatchLaneCandidate{
			TaskID:        row.TaskID,
			LaneID:        laneID,
			PluginID:      strings.TrimSpace(row.PluginID),
			DispatchClass: buildDispatchClassKey(strings.TrimSpace(row.PluginID), toResourceSummary(row.ResourcesRaw)),
			ReadyAt:       readyAt,
			IsReady:       normalizeTaskEnumText(string(row.Status)) == "READY",
		})
		s.touchLaneState(laneID, now)
	}
	s.pruneLaneState(now.Add(-24 * time.Hour))
	return candidates, nil
}

func buildDispatchClassKey(pluginID string, resources *runtimecontrolv1.ResourceSummary) string {
	pluginID = strings.TrimSpace(pluginID)
	resourceParts := make([]string, 0, 4)
	if resources != nil {
		accelerators := make([]string, 0, len(resources.GetAccelerators()))
		for _, item := range resources.GetAccelerators() {
			if item == nil {
				continue
			}
			acceleratorType := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(item.GetType().String(), "ACCELERATOR_TYPE_")))
			if acceleratorType == "" || acceleratorType == "unspecified" {
				continue
			}
			accelerators = append(accelerators, acceleratorType)
		}
		sort.Strings(accelerators)
		resourceParts = append(resourceParts, accelerators...)
		if resources.GetGpuCount() > 0 {
			resourceParts = append(resourceParts, "gpu")
		}
	}
	if len(resourceParts) == 0 {
		resourceParts = append(resourceParts, "default")
	}
	return pluginID + "|" + strings.Join(resourceParts, ",")
}

func (s *Service) selectDispatchPass(candidates []dispatchLaneCandidate, limit int) []dispatchLaneCandidate {
	if len(candidates) == 0 || limit <= 0 {
		return nil
	}
	byClass := make(map[string][]dispatchLaneCandidate)
	classKeys := make([]string, 0)
	for _, candidate := range candidates {
		classKey := candidate.DispatchClass
		if _, exists := byClass[classKey]; !exists {
			classKeys = append(classKeys, classKey)
		}
		byClass[classKey] = append(byClass[classKey], candidate)
	}
	sort.Strings(classKeys)
	for _, classKey := range classKeys {
		rows := byClass[classKey]
		sort.Slice(rows, func(i, j int) bool {
			left := s.getLaneState(rows[i].LaneID)
			right := s.getLaneState(rows[j].LaneID)
			if left.SkipRounds != right.SkipRounds {
				return left.SkipRounds > right.SkipRounds
			}
			if !rows[i].ReadyAt.Equal(rows[j].ReadyAt) {
				return rows[i].ReadyAt.Before(rows[j].ReadyAt)
			}
			if !left.LastDispatchAt.Equal(right.LastDispatchAt) {
				if left.LastDispatchAt.IsZero() {
					return true
				}
				if right.LastDispatchAt.IsZero() {
					return false
				}
				return left.LastDispatchAt.Before(right.LastDispatchAt)
			}
			return rows[i].LaneID < rows[j].LaneID
		})
		byClass[classKey] = rows
	}
	selected := make([]dispatchLaneCandidate, 0, minInt(limit, len(candidates)))
	for len(selected) < limit {
		progress := false
		for _, classKey := range classKeys {
			rows := byClass[classKey]
			if len(rows) == 0 {
				continue
			}
			selected = append(selected, rows[0])
			byClass[classKey] = rows[1:]
			progress = true
			if len(selected) >= limit {
				break
			}
		}
		if !progress {
			break
		}
	}
	return selected
}

func (s *Service) touchLaneState(laneID string, now time.Time) {
	laneID = strings.TrimSpace(laneID)
	if laneID == "" {
		return
	}
	s.laneStateMu.Lock()
	defer s.laneStateMu.Unlock()
	state := s.laneState[laneID]
	state.LastSeenAt = now.UTC()
	s.laneState[laneID] = state
}

func (s *Service) incrementLaneSkip(laneID string) {
	laneID = strings.TrimSpace(laneID)
	if laneID == "" {
		return
	}
	s.laneStateMu.Lock()
	defer s.laneStateMu.Unlock()
	state := s.laneState[laneID]
	state.SkipRounds++
	state.LastSeenAt = time.Now().UTC()
	s.laneState[laneID] = state
}

func (s *Service) recordLaneDispatch(laneID string) {
	laneID = strings.TrimSpace(laneID)
	if laneID == "" {
		return
	}
	s.laneStateMu.Lock()
	defer s.laneStateMu.Unlock()
	state := s.laneState[laneID]
	state.SkipRounds = 0
	state.LastDispatchAt = time.Now().UTC()
	state.LastSeenAt = state.LastDispatchAt
	s.laneState[laneID] = state
}

func (s *Service) getLaneState(laneID string) dispatchLaneState {
	laneID = strings.TrimSpace(laneID)
	if laneID == "" {
		return dispatchLaneState{}
	}
	s.laneStateMu.Lock()
	defer s.laneStateMu.Unlock()
	return s.laneState[laneID]
}

func (s *Service) pruneLaneState(cutoff time.Time) {
	s.laneStateMu.Lock()
	defer s.laneStateMu.Unlock()
	for laneID, state := range s.laneState {
		if state.LastSeenAt.IsZero() || state.LastSeenAt.Before(cutoff) {
			delete(s.laneState, laneID)
		}
	}
}
