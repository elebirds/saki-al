package config

import "testing"

func TestLoadConfigDefaults(t *testing.T) {
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.PublicAPIBind == "" || cfg.RuntimeBind == "" {
		t.Fatal("default binds must be set")
	}
}
