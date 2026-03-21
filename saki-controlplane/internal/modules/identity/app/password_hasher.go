package app

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"

	"golang.org/x/crypto/argon2"
)

const argon2Version = 0x13

var ErrInvalidPasswordHash = errors.New("invalid password hash")

type PasswordHasher struct {
	memory      uint32
	iterations  uint32
	parallelism uint8
	saltLength  uint32
	keyLength   uint32
	rand        io.Reader
}

func NewPasswordHasher() *PasswordHasher {
	return &PasswordHasher{
		memory:      64 * 1024,
		iterations:  3,
		parallelism: 2,
		saltLength:  16,
		keyLength:   32,
		rand:        rand.Reader,
	}
}

func (h *PasswordHasher) Hash(password string) (string, error) {
	salt := make([]byte, h.saltLength)
	if _, err := io.ReadFull(h.rand, salt); err != nil {
		return "", err
	}

	sum := argon2.IDKey([]byte(password), salt, h.iterations, h.memory, h.parallelism, h.keyLength)
	return fmt.Sprintf(
		"$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s",
		argon2Version,
		h.memory,
		h.iterations,
		h.parallelism,
		base64.RawStdEncoding.EncodeToString(salt),
		base64.RawStdEncoding.EncodeToString(sum),
	), nil
}

func (h *PasswordHasher) Verify(password string, encoded string) (bool, error) {
	params, salt, expected, err := parseArgon2idPHC(encoded)
	if err != nil {
		return false, err
	}

	actual := argon2.IDKey([]byte(password), salt, params.iterations, params.memory, params.parallelism, uint32(len(expected)))
	return subtle.ConstantTimeCompare(actual, expected) == 1, nil
}

type parsedArgon2Params struct {
	memory      uint32
	iterations  uint32
	parallelism uint8
}

func parseArgon2idPHC(encoded string) (parsedArgon2Params, []byte, []byte, error) {
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || parts[1] != "argon2id" {
		return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
	}

	versionPart := strings.TrimPrefix(parts[2], "v=")
	version, err := strconv.Atoi(versionPart)
	if err != nil || version != argon2Version {
		return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
	}

	var params parsedArgon2Params
	for _, piece := range strings.Split(parts[3], ",") {
		key, value, ok := strings.Cut(piece, "=")
		if !ok {
			return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
		}
		switch key {
		case "m":
			v, err := strconv.ParseUint(value, 10, 32)
			if err != nil {
				return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
			}
			params.memory = uint32(v)
		case "t":
			v, err := strconv.ParseUint(value, 10, 32)
			if err != nil {
				return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
			}
			params.iterations = uint32(v)
		case "p":
			v, err := strconv.ParseUint(value, 10, 8)
			if err != nil {
				return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
			}
			params.parallelism = uint8(v)
		default:
			return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
		}
	}
	if params.memory == 0 || params.iterations == 0 || params.parallelism == 0 {
		return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
	}

	salt, err := base64.RawStdEncoding.DecodeString(parts[4])
	if err != nil {
		return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
	}
	sum, err := base64.RawStdEncoding.DecodeString(parts[5])
	if err != nil || len(sum) == 0 {
		return parsedArgon2Params{}, nil, nil, ErrInvalidPasswordHash
	}

	return params, salt, sum, nil
}
