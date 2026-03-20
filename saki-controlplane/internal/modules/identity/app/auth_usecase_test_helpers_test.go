package app

import (
	"context"
	"net/netip"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

type fakeIdentityAccessTokenIssuer struct {
	token       string
	err         error
	calls       []string
	permissions []string
}

func (f *fakeIdentityAccessTokenIssuer) IssueTokenContext(_ context.Context, userID string) (string, error) {
	f.calls = append(f.calls, userID)
	if f.err != nil {
		return "", f.err
	}
	return f.token, nil
}

func (f *fakeIdentityAccessTokenIssuer) ParseToken(token string) (*accessapp.Claims, error) {
	if f.err != nil {
		return nil, f.err
	}
	return &accessapp.Claims{
		UserID:      token,
		Permissions: append([]string(nil), f.permissions...),
	}, nil
}

type fakeIdentityOpaqueTokenIssuer struct {
	token string
	hash  string
	err   error
}

func (f *fakeIdentityOpaqueTokenIssuer) IssueOpaqueToken() (string, string, error) {
	if f.err != nil {
		return "", "", f.err
	}
	return f.token, f.hash, nil
}

type fakeRefreshSessionManager struct {
	issue       *RefreshSessionIssue
	issueErr    error
	rotate      *RefreshSessionIssue
	rotateErr   error
	issueCalls  []fakeRefreshIssueCall
	rotateCalls []fakeRefreshRotateCall
}

type fakeRefreshIssueCall struct {
	PrincipalID uuid.UUID
	UserAgent   string
	IPAddress   *netip.Addr
}

type fakeRefreshRotateCall struct {
	RefreshToken string
	UserAgent    string
	IPAddress    *netip.Addr
}

func (f *fakeRefreshSessionManager) Issue(_ context.Context, principalID uuid.UUID, userAgent string, ipAddress *netip.Addr) (*RefreshSessionIssue, error) {
	f.issueCalls = append(f.issueCalls, fakeRefreshIssueCall{
		PrincipalID: principalID,
		UserAgent:   userAgent,
		IPAddress:   cloneTestAddr(ipAddress),
	})
	if f.issueErr != nil {
		return nil, f.issueErr
	}
	return cloneRefreshIssue(f.issue), nil
}

func (f *fakeRefreshSessionManager) Rotate(_ context.Context, refreshToken string, userAgent string, ipAddress *netip.Addr) (*RefreshSessionIssue, error) {
	f.rotateCalls = append(f.rotateCalls, fakeRefreshRotateCall{
		RefreshToken: refreshToken,
		UserAgent:    userAgent,
		IPAddress:    cloneTestAddr(ipAddress),
	})
	if f.rotateErr != nil {
		return nil, f.rotateErr
	}
	return cloneRefreshIssue(f.rotate), nil
}

func cloneRefreshIssue(issue *RefreshSessionIssue) *RefreshSessionIssue {
	if issue == nil {
		return nil
	}
	copy := *issue
	copy.Session = cloneRefreshSession(issue.Session)
	return &copy
}

func cloneTestAddr(addr *netip.Addr) *netip.Addr {
	if addr == nil {
		return nil
	}
	copy := *addr
	return &copy
}

func testStringPtr(value string) *string {
	copy := value
	return &copy
}

func newTestRefreshSession(principalID uuid.UUID) *identitydomain.RefreshSession {
	return &identitydomain.RefreshSession{
		ID:          uuid.New(),
		PrincipalID: principalID,
		FamilyID:    uuid.New(),
	}
}
