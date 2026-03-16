package protocol

import (
	"bytes"
	"testing"
)

func TestFrameRoundTrip(t *testing.T) {
	var buf bytes.Buffer
	payload := []byte(`{"kind":"progress","percent":42}`)

	if err := WriteFrame(&buf, payload); err != nil {
		t.Fatalf("write frame: %v", err)
	}

	got, err := ReadFrame(&buf)
	if err != nil {
		t.Fatalf("read frame: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("unexpected payload: %q", got)
	}
}

func TestReadFrameRejectsShortPayload(t *testing.T) {
	buf := bytes.NewBuffer([]byte{0x00, 0x00, 0x00})

	if _, err := ReadFrame(buf); err == nil {
		t.Fatal("expected read frame to fail")
	}
}
