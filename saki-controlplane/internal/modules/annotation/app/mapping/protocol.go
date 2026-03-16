package mapping

import (
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"

	workerv1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/worker/v1"
	"google.golang.org/protobuf/proto"
)

type frameKind byte

const (
	frameKindExecuteRequest frameKind = 1
	frameKindExecuteResult  frameKind = 3
)

type MapFedoOBBRequest struct {
	SourceView       string         `json:"-"`
	TargetView       string         `json:"-"`
	SourceGeometry   map[string]any `json:"-"`
	LookupTable      []byte         `json:"-"`
	TimeGapThreshold int            `json:"-"`
}

type mapResponse struct {
	MappedGeometries []map[string]any `json:"mapped_geometries"`
}

func encodeMapRequest(req MapFedoOBBRequest) ([]byte, error) {
	type payload struct {
		SourceView       string         `json:"source_view"`
		TargetView       string         `json:"target_view"`
		SourceGeometry   map[string]any `json:"source_geometry"`
		LookupTableB64   string         `json:"lookup_table_b64"`
		TimeGapThreshold int            `json:"time_gap_threshold,omitempty"`
	}

	return json.Marshal(payload{
		SourceView:       req.SourceView,
		TargetView:       req.TargetView,
		SourceGeometry:   req.SourceGeometry,
		LookupTableB64:   base64.StdEncoding.EncodeToString(req.LookupTable),
		TimeGapThreshold: req.TimeGapThreshold,
	})
}

func decodeMapResponse(payload []byte) (mapResponse, error) {
	var response mapResponse
	err := json.Unmarshal(payload, &response)
	return response, err
}

func writeExecuteRequest(w io.Writer, req *workerv1.ExecuteRequest) error {
	return writeMessage(w, frameKindExecuteRequest, req)
}

func readExecuteRequest(r io.Reader) (*workerv1.ExecuteRequest, error) {
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

func writeExecuteResult(w io.Writer, response mapResponse) error {
	payload, err := json.Marshal(response)
	if err != nil {
		return err
	}

	return writeMessage(w, frameKindExecuteResult, &workerv1.ExecuteResult{
		RequestId: "mapping-result",
		Ok:        true,
		Payload:   payload,
	})
}

func readExecuteResult(r io.Reader) (*workerv1.ExecuteResult, error) {
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

func writeMessage(w io.Writer, kind frameKind, msg proto.Message) error {
	payload, err := proto.Marshal(msg)
	if err != nil {
		return err
	}

	frame := append([]byte{byte(kind)}, payload...)
	return writeFrame(w, frame)
}

func readMessage(r io.Reader, expected frameKind) ([]byte, error) {
	frame, err := readFrame(r)
	if err != nil {
		return nil, err
	}
	if len(frame) == 0 {
		return nil, io.ErrUnexpectedEOF
	}
	if frameKind(frame[0]) != expected {
		return nil, errors.New("unexpected frame kind")
	}
	return frame[1:], nil
}

func writeFrame(w io.Writer, payload []byte) error {
	header := make([]byte, 4)
	binary.BigEndian.PutUint32(header, uint32(len(payload)))
	if _, err := w.Write(header); err != nil {
		return err
	}
	_, err := w.Write(payload)
	return err
}

func readFrame(r io.Reader) ([]byte, error) {
	header := make([]byte, 4)
	if _, err := io.ReadFull(r, header); err != nil {
		return nil, err
	}

	size := binary.BigEndian.Uint32(header)
	payload := make([]byte, size)
	if _, err := io.ReadFull(r, payload); err != nil {
		return nil, err
	}

	return payload, nil
}
