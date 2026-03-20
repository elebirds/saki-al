package app

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
)

func TestCredentialVerifierSupportsArgon2idAndLegacyScheme(t *testing.T) {
	hasher := NewPasswordHasher()
	verifier := NewCredentialVerifier(hasher)

	const rawPassword = "Saki-Password-123!"

	currentHash, err := hasher.Hash(rawPassword)
	if err != nil {
		t.Fatalf("hash current password: %v", err)
	}

	legacyDigest := sha256.Sum256([]byte(rawPassword))
	legacyHash, err := hasher.Hash(hex.EncodeToString(legacyDigest[:]))
	if err != nil {
		t.Fatalf("hash legacy password: %v", err)
	}

	ok, err := verifier.Verify(identitydomain.PasswordCredential{
		Provider:     identitydomain.CredentialProviderLocalPassword,
		Scheme:       identitydomain.PasswordSchemeArgon2id,
		PasswordHash: currentHash,
	}, rawPassword)
	if err != nil {
		t.Fatalf("verify current scheme: %v", err)
	}
	if !ok {
		t.Fatal("expected current password scheme to verify")
	}

	ok, err = verifier.Verify(identitydomain.PasswordCredential{
		Provider:     identitydomain.CredentialProviderLocalPassword,
		Scheme:       identitydomain.PasswordSchemeLegacyFrontendSHA256Argon2,
		PasswordHash: legacyHash,
	}, rawPassword)
	if err != nil {
		t.Fatalf("verify legacy scheme: %v", err)
	}
	if !ok {
		t.Fatal("expected legacy password scheme to verify with raw password input")
	}
}

func TestCredentialVerifierRejectsUnsupportedProvider(t *testing.T) {
	verifier := NewCredentialVerifier(NewPasswordHasher())

	_, err := verifier.Verify(identitydomain.PasswordCredential{
		Provider:     "oidc",
		Scheme:       identitydomain.PasswordSchemeArgon2id,
		PasswordHash: "unused",
	}, "secret")
	if err == nil {
		t.Fatal("expected unsupported provider to fail")
	}
}
