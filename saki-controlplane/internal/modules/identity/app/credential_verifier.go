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
	// 关键设计：当前 controlplane 只落地 local_password，
	// 这样可以先把密码协议、旧哈希兼容与测试边界固定住，而不提前引入外部 provider 框架的伪抽象。
	if credential.Provider != identitydomain.CredentialProviderLocalPassword {
		return false, ErrUnsupportedCredentialProvider
	}

	switch credential.Scheme {
	case identitydomain.PasswordSchemeArgon2id:
		return v.hasher.Verify(rawPassword, credential.PasswordHash)
	case identitydomain.PasswordSchemeLegacyFrontendSHA256Argon2:
		return v.hasher.Verify(legacyFrontendPasswordDigest(rawPassword), credential.PasswordHash)
	default:
		return false, ErrUnsupportedCredentialScheme
	}
}
