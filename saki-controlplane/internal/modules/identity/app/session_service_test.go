package app

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/netip"
	"testing"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

func TestSessionServiceRotatesRefreshSessionWithinSameFamily(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 3, 20, 10, 0, 0, 0, time.UTC)
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000123")
	ip := netip.MustParseAddr("192.168.1.8")

	store := newFakeSessionStore()
	issuer := NewTokenIssuer()
	issuer.now = func() time.Time { return now }
	issuer.rand = bytes.NewReader(sequentialBytes(128))

	service := NewSessionService(store, issuer)
	service.now = func() time.Time { return now }

	issued, err := service.Issue(ctx, principalID, "browser-a", &ip)
	if err != nil {
		t.Fatalf("issue refresh session: %v", err)
	}

	rotated, err := service.Rotate(ctx, issued.RefreshToken, "browser-b", &ip)
	if err != nil {
		t.Fatalf("rotate refresh session: %v", err)
	}

	if rotated.RefreshToken == issued.RefreshToken {
		t.Fatal("expected rotated refresh token to change")
	}
	if rotated.Session.ID == issued.Session.ID {
		t.Fatal("expected rotation to create a new session row")
	}
	if rotated.Session.PrincipalID != principalID {
		t.Fatalf("unexpected principal id after rotation: %+v", rotated.Session)
	}
	if got, want := rotated.Session.ExpiresAt, now.Add(DefaultRefreshSessionTTL); !got.Equal(want) {
		t.Fatalf("expires_at got %s want %s", got, want)
	}
	if got, want := rotated.Session.LastSeenAt, now; !got.Equal(want) {
		t.Fatalf("last_seen_at got %s want %s", got, want)
	}
	if got, want := rotated.Session.UserAgent, "browser-b"; got != want {
		t.Fatalf("user_agent got %q want %q", got, want)
	}
	if rotated.Session.IPAddress == nil || *rotated.Session.IPAddress != ip {
		t.Fatalf("unexpected ip address: %+v", rotated.Session.IPAddress)
	}
	if rotated.Session.FamilyID != issued.Session.FamilyID {
		t.Fatalf("expected rotated session to stay in family %s, got %s", issued.Session.FamilyID, rotated.Session.FamilyID)
	}
	if rotated.Session.RotatedFrom == nil || *rotated.Session.RotatedFrom != issued.Session.ID {
		t.Fatalf("expected rotated_from=%s, got %+v", issued.Session.ID, rotated.Session.RotatedFrom)
	}

	current := store.byHash[issued.Session.TokenHash]
	if current == nil {
		t.Fatal("expected old session row to remain for replay detection")
	}
	if current.ReplacedBy == nil || *current.ReplacedBy != rotated.Session.ID {
		t.Fatalf("expected old session to point at replacement %s, got %+v", rotated.Session.ID, current.ReplacedBy)
	}
	if current.RevokedAt == nil || !current.RevokedAt.Equal(now) {
		t.Fatalf("expected old session revoked at %s, got %+v", now, current.RevokedAt)
	}
}

func TestSessionServiceRotateRevokesFamilyOnReplay(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 3, 20, 11, 0, 0, 0, time.UTC)
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000124")

	store := newFakeSessionStore()
	issuer := NewTokenIssuer()
	issuer.now = func() time.Time { return now }
	issuer.rand = bytes.NewReader(sequentialBytes(128))

	service := NewSessionService(store, issuer)
	service.now = func() time.Time { return now }

	issued, err := service.Issue(ctx, principalID, "browser-a", nil)
	if err != nil {
		t.Fatalf("issue refresh session: %v", err)
	}
	rotated, err := service.Rotate(ctx, issued.RefreshToken, "browser-b", nil)
	if err != nil {
		t.Fatalf("rotate refresh session: %v", err)
	}

	_, err = service.Rotate(ctx, issued.RefreshToken, "browser-c", nil)
	if !errors.Is(err, ErrRefreshSessionReplayDetected) {
		t.Fatalf("expected replay to revoke family, got %v", err)
	}

	current := store.byHash[issued.Session.TokenHash]
	next := store.byHash[rotated.Session.TokenHash]
	if current == nil || next == nil {
		t.Fatalf("expected replay test family rows to stay queryable, current=%+v next=%+v", current, next)
	}
	if current.ReplayDetectedAt == nil || !current.ReplayDetectedAt.Equal(now) {
		t.Fatalf("expected old session replay_detected_at=%s, got %+v", now, current.ReplayDetectedAt)
	}
	if next.ReplayDetectedAt == nil || !next.ReplayDetectedAt.Equal(now) {
		t.Fatalf("expected rotated session replay_detected_at=%s, got %+v", now, next.ReplayDetectedAt)
	}
	if next.RevokedAt == nil || !next.RevokedAt.Equal(now) {
		t.Fatalf("expected rotated session to be revoked on family replay, got %+v", next.RevokedAt)
	}
}

func TestSessionServiceRotatePreservesCurrentSessionOnIssueFailure(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 3, 20, 12, 0, 0, 0, time.UTC)
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000125")

	store := newFakeSessionStore()
	issuer := NewTokenIssuer()
	issuer.now = func() time.Time { return now }
	issuer.rand = bytes.NewReader(sequentialBytes(64))

	service := NewSessionService(store, issuer)
	service.now = func() time.Time { return now }

	issued, err := service.Issue(ctx, principalID, "browser-a", nil)
	if err != nil {
		t.Fatalf("issue refresh session: %v", err)
	}

	store.createErr = io.ErrUnexpectedEOF

	_, err = service.Rotate(ctx, issued.RefreshToken, "browser-b", nil)
	if !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Fatalf("expected rotate to surface create failure, got %v", err)
	}

	current := store.byHash[issued.Session.TokenHash]
	if current == nil {
		t.Fatal("expected old refresh session to remain after failed rotation")
	}
	if current.ReplacedBy != nil || current.RevokedAt != nil {
		t.Fatalf("expected failed rotation not to mutate current session, got %+v", current)
	}
}

func TestSessionServiceRevokeRevokesCurrentSession(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 3, 20, 13, 0, 0, 0, time.UTC)
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000126")

	store := newFakeSessionStore()
	issuer := NewTokenIssuer()
	issuer.now = func() time.Time { return now }
	issuer.rand = bytes.NewReader(sequentialBytes(64))

	service := NewSessionService(store, issuer)
	service.now = func() time.Time { return now }

	issued, err := service.Issue(ctx, principalID, "browser-a", nil)
	if err != nil {
		t.Fatalf("issue refresh session: %v", err)
	}

	if err := service.Revoke(ctx, issued.RefreshToken); err != nil {
		t.Fatalf("revoke refresh session: %v", err)
	}

	current := store.byHash[issued.Session.TokenHash]
	if current == nil || current.RevokedAt == nil || !current.RevokedAt.Equal(now) {
		t.Fatalf("expected session revoked at %s, got %+v", now, current)
	}

	_, err = service.Rotate(ctx, issued.RefreshToken, "browser-b", nil)
	if !errors.Is(err, ErrInvalidRefreshSession) {
		t.Fatalf("expected revoked session to become invalid, got %v", err)
	}
}

type fakeSessionStore struct {
	byHash         map[string]*identitydomain.RefreshSession
	createErr      error
	rotateErr      error
	revokeErr      error
	revokeFamilyErr error
}

func newFakeSessionStore() *fakeSessionStore {
	return &fakeSessionStore{
		byHash: map[string]*identitydomain.RefreshSession{},
	}
}

func (s *fakeSessionStore) CreateRefreshSession(_ context.Context, params CreateRefreshSessionParams) (*identitydomain.RefreshSession, error) {
	if s.createErr != nil {
		return nil, s.createErr
	}
	familyID := params.FamilyID
	if familyID == uuid.Nil {
		familyID = uuid.New()
	}
	session := &identitydomain.RefreshSession{
		ID:          uuid.New(),
		PrincipalID: params.PrincipalID,
		FamilyID:    familyID,
		TokenHash:   params.TokenHash,
		UserAgent:   params.UserAgent,
		IPAddress:   params.IPAddress,
		LastSeenAt:  params.LastSeenAt,
		ExpiresAt:   params.ExpiresAt,
		CreatedAt:   params.LastSeenAt,
		UpdatedAt:   params.LastSeenAt,
	}
	if params.RotatedFrom != nil {
		copyID := *params.RotatedFrom
		session.RotatedFrom = &copyID
	}
	s.byHash[session.TokenHash] = cloneRefreshSession(session)
	return cloneRefreshSession(session), nil
}

func (s *fakeSessionStore) GetRefreshSessionByTokenHash(_ context.Context, tokenHash string) (*identitydomain.RefreshSession, error) {
	return cloneRefreshSession(s.byHash[tokenHash]), nil
}

func (s *fakeSessionStore) RotateRefreshSession(_ context.Context, params RotateRefreshSessionParams) (*identitydomain.RefreshSession, error) {
	if s.rotateErr != nil {
		return nil, s.rotateErr
	}
	current, ok := s.byHash[params.CurrentTokenHash]
	if !ok || current.IsExpired(params.Now) {
		return nil, ErrRefreshSessionNotConsumed
	}
	if current.ReplacedBy != nil {
		for _, session := range s.byHash {
			if session.FamilyID != current.FamilyID {
				continue
			}
			session.ReplayDetectedAt = timePtr(params.Now)
			if session.RevokedAt == nil {
				session.RevokedAt = timePtr(params.Now)
			}
			session.UpdatedAt = params.Now
		}
		return nil, ErrRefreshSessionReplayDetected
	}
	if current.RevokedAt != nil {
		return nil, ErrRefreshSessionNotConsumed
	}
	if s.createErr != nil {
		return nil, s.createErr
	}

	newSession := &identitydomain.RefreshSession{
		ID:          uuid.New(),
		PrincipalID: current.PrincipalID,
		FamilyID:    current.FamilyID,
		TokenHash:   params.NewTokenHash,
		UserAgent:   params.UserAgent,
		IPAddress:   params.IPAddress,
		LastSeenAt:  params.Now,
		ExpiresAt:   params.ExpiresAt,
		CreatedAt:   params.Now,
		UpdatedAt:   params.Now,
		RotatedFrom: uuidPtr(current.ID),
	}

	current.ReplacedBy = uuidPtr(newSession.ID)
	current.RevokedAt = timePtr(params.Now)
	current.LastSeenAt = params.Now
	current.UpdatedAt = params.Now
	s.byHash[current.TokenHash] = cloneRefreshSession(current)
	s.byHash[newSession.TokenHash] = cloneRefreshSession(newSession)
	return cloneRefreshSession(newSession), nil
}

func (s *fakeSessionStore) RevokeRefreshSessionByTokenHash(_ context.Context, tokenHash string, now time.Time) error {
	if s.revokeErr != nil {
		return s.revokeErr
	}
	current, ok := s.byHash[tokenHash]
	if !ok || current.IsExpired(now) {
		return ErrRefreshSessionNotConsumed
	}
	if current.RevokedAt != nil {
		return ErrRefreshSessionNotConsumed
	}
	current.RevokedAt = timePtr(now)
	current.UpdatedAt = now
	s.byHash[tokenHash] = cloneRefreshSession(current)
	return nil
}

func (s *fakeSessionStore) RevokeRefreshSessionFamily(_ context.Context, familyID uuid.UUID, now time.Time) error {
	if s.revokeFamilyErr != nil {
		return s.revokeFamilyErr
	}
	for _, session := range s.byHash {
		if session.FamilyID != familyID {
			continue
		}
		session.ReplayDetectedAt = timePtr(now)
		if session.RevokedAt == nil {
			session.RevokedAt = timePtr(now)
		}
		session.UpdatedAt = now
	}
	return nil
}

func cloneRefreshSession(session *identitydomain.RefreshSession) *identitydomain.RefreshSession {
	if session == nil {
		return nil
	}
	copy := *session
	if session.IPAddress != nil {
		ip := *session.IPAddress
		copy.IPAddress = &ip
	}
	if session.RotatedFrom != nil {
		id := *session.RotatedFrom
		copy.RotatedFrom = &id
	}
	if session.ReplacedBy != nil {
		id := *session.ReplacedBy
		copy.ReplacedBy = &id
	}
	if session.RevokedAt != nil {
		ts := *session.RevokedAt
		copy.RevokedAt = &ts
	}
	if session.ReplayDetectedAt != nil {
		ts := *session.ReplayDetectedAt
		copy.ReplayDetectedAt = &ts
	}
	return &copy
}

func timePtr(value time.Time) *time.Time {
	copy := value
	return &copy
}

func uuidPtr(value uuid.UUID) *uuid.UUID {
	copy := value
	return &copy
}

func sequentialBytes(size int) []byte {
	buf := make([]byte, size)
	for i := range buf {
		buf[i] = byte(i)
	}
	return buf
}
