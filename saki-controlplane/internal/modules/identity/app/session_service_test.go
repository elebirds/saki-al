package app

import (
	"bytes"
	"context"
	"errors"
	"net/netip"
	"testing"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

func TestSessionServiceRotatesRefreshSession(t *testing.T) {
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

	if store.deleted[issued.Session.ID] != 1 {
		t.Fatalf("expected old session to be deleted once, got %+v", store.deleted)
	}
	if _, ok := store.byHash[issued.Session.TokenHash]; ok {
		t.Fatal("expected old token hash to be removed after rotation")
	}

	_, err = service.Rotate(ctx, issued.RefreshToken, "browser-c", &ip)
	if !errors.Is(err, ErrInvalidRefreshSession) {
		t.Fatalf("expected old refresh token to become invalid, got %v", err)
	}
}

type fakeSessionStore struct {
	byHash  map[string]*identitydomain.RefreshSession
	deleted map[uuid.UUID]int
}

func newFakeSessionStore() *fakeSessionStore {
	return &fakeSessionStore{
		byHash:  map[string]*identitydomain.RefreshSession{},
		deleted: map[uuid.UUID]int{},
	}
}

func (s *fakeSessionStore) CreateRefreshSession(_ context.Context, params CreateRefreshSessionParams) (*identitydomain.RefreshSession, error) {
	session := &identitydomain.RefreshSession{
		ID:          uuid.New(),
		PrincipalID: params.PrincipalID,
		TokenHash:   params.TokenHash,
		UserAgent:   params.UserAgent,
		IPAddress:   params.IPAddress,
		LastSeenAt:  params.LastSeenAt,
		ExpiresAt:   params.ExpiresAt,
		CreatedAt:   params.LastSeenAt,
		UpdatedAt:   params.LastSeenAt,
	}
	s.byHash[session.TokenHash] = session
	return cloneRefreshSession(session), nil
}

func (s *fakeSessionStore) GetRefreshSessionByTokenHash(_ context.Context, tokenHash string) (*identitydomain.RefreshSession, error) {
	session := s.byHash[tokenHash]
	return cloneRefreshSession(session), nil
}

func (s *fakeSessionStore) DeleteRefreshSession(_ context.Context, id uuid.UUID) error {
	s.deleted[id]++
	for hash, session := range s.byHash {
		if session.ID == id {
			delete(s.byHash, hash)
			break
		}
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
	return &copy
}

func sequentialBytes(size int) []byte {
	buf := make([]byte, size)
	for i := range buf {
		buf[i] = byte(i)
	}
	return buf
}
