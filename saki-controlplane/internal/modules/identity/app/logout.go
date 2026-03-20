package app

import "context"

type LogoutCommand struct {
	RefreshToken string
}

type RefreshSessionRevoker interface {
	Revoke(ctx context.Context, refreshToken string) error
}

type LogoutUseCase struct {
	sessions RefreshSessionRevoker
}

func NewLogoutUseCase(sessions RefreshSessionRevoker) *LogoutUseCase {
	return &LogoutUseCase{sessions: sessions}
}

func (u *LogoutUseCase) Execute(ctx context.Context, cmd LogoutCommand) error {
	return u.sessions.Revoke(ctx, cmd.RefreshToken)
}
