package app

import (
	"errors"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
)

var (
	ErrUnsupportedCredentialProvider = errors.New("unsupported credential provider")
	ErrUnsupportedCredentialScheme   = errors.New("unsupported credential scheme")
)

type CredentialVerifier struct {
	hasher *PasswordHasher
}

func NewCredentialVerifier(hasher *PasswordHasher) *CredentialVerifier {
	if hasher == nil {
		hasher = NewPasswordHasher()
	}
	return &CredentialVerifier{hasher: hasher}
}

func (v *CredentialVerifier) Verify(credential identitydomain.PasswordCredential, rawPassword string) (bool, error) {
	// 关键设计：controlplane 当前只接受 local_password + argon2id 这一条 canonical 密码协议。
	// 旧前端预哈希方案已经退役；未来若接 OIDC 等外部 provider，应新增独立 provider 语义而不是复活历史密码别名。
	if credential.Provider != identitydomain.CredentialProviderLocalPassword {
		return false, ErrUnsupportedCredentialProvider
	}

	switch credential.Scheme {
	case identitydomain.PasswordSchemeArgon2id:
		return v.hasher.Verify(rawPassword, credential.PasswordHash)
	default:
		return false, ErrUnsupportedCredentialScheme
	}
}
