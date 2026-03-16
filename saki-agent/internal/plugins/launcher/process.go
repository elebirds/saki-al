package launcher

import (
	"errors"
	"io"

	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
	baseprotocol "github.com/elebirds/saki/saki-agent/internal/plugins/protocol"
	"google.golang.org/protobuf/proto"
)

type frameKind byte

const (
	frameKindExecuteRequest frameKind = 1
	frameKindWorkerEvent    frameKind = 2
	frameKindExecuteResult  frameKind = 3
)

func WriteExecuteRequest(w io.Writer, req *workerv1.ExecuteRequest) error {
	return writeMessage(w, frameKindExecuteRequest, req)
}

func ReadExecuteRequest(r io.Reader) (*workerv1.ExecuteRequest, error) {
	payload, err := readMessage(r, frameKindExecuteRequest)
	if err != nil {
		return nil, err
	}

	var req workerv1.ExecuteRequest
	if err := proto.Unmarshal(payload, &req); err != nil {
		return nil, err
	}
	return &req, nil
}

func WriteWorkerEvent(w io.Writer, event *workerv1.WorkerEvent) error {
	return writeMessage(w, frameKindWorkerEvent, event)
}

func ReadWorkerEvent(r io.Reader) (*workerv1.WorkerEvent, error) {
	payload, err := readMessage(r, frameKindWorkerEvent)
	if err != nil {
		return nil, err
	}

	var event workerv1.WorkerEvent
	if err := proto.Unmarshal(payload, &event); err != nil {
		return nil, err
	}
	return &event, nil
}

func WriteExecuteResult(w io.Writer, result *workerv1.ExecuteResult) error {
	return writeMessage(w, frameKindExecuteResult, result)
}

func ReadExecuteResult(r io.Reader) (*workerv1.ExecuteResult, error) {
	payload, err := readMessage(r, frameKindExecuteResult)
	if err != nil {
		return nil, err
	}

	var result workerv1.ExecuteResult
	if err := proto.Unmarshal(payload, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

func ReadEnvelope(r io.Reader) (frameKind, []byte, error) {
	frame, err := baseprotocol.ReadFrame(r)
	if err != nil {
		return 0, nil, err
	}
	if len(frame) == 0 {
		return 0, nil, io.ErrUnexpectedEOF
	}

	return frameKind(frame[0]), frame[1:], nil
}

func writeMessage(w io.Writer, kind frameKind, msg proto.Message) error {
	payload, err := proto.Marshal(msg)
	if err != nil {
		return err
	}

	frame := append([]byte{byte(kind)}, payload...)
	return baseprotocol.WriteFrame(w, frame)
}

func readMessage(r io.Reader, expected frameKind) ([]byte, error) {
	kind, payload, err := ReadEnvelope(r)
	if err != nil {
		return nil, err
	}
	if kind != expected {
		return nil, errors.New("unexpected frame kind")
	}
	return payload, nil
}
