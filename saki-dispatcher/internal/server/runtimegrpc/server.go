package runtimegrpc

import (
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"
	"google.golang.org/grpc/peer"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-dispatcher/internal/controlplane"
	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

type Server struct {
	runtimecontrolv1.UnimplementedRuntimeControlServer

	dispatcher   *dispatch.Dispatcher
	controlPlane *controlplane.Service
	domainClient *runtime_domain_client.Client
	logger       zerolog.Logger
}

func NewServer(
	dispatcher *dispatch.Dispatcher,
	controlPlane *controlplane.Service,
	domainClient *runtime_domain_client.Client,
	logger zerolog.Logger,
) *Server {
	return &Server{
		dispatcher:   dispatcher,
		controlPlane: controlPlane,
		domainClient: domainClient,
		logger:       logger,
	}
}

func (s *Server) Stream(stream runtimecontrolv1.RuntimeControl_StreamServer) (retErr error) {
	var executorID string
	peerAddr := streamPeerAddr(stream.Context())
	s.logger.Info().Str("peer", peerAddr).Msg("runtime stream connected")

	defer func() {
		if executorID != "" {
			s.dispatcher.UnregisterExecutor(executorID)
			disconnectReason := ""
			if retErr != nil && retErr != io.EOF {
				disconnectReason = retErr.Error()
			}
			if s.controlPlane != nil {
				if err := s.controlPlane.OnExecutorDisconnected(context.Background(), executorID, disconnectReason); err != nil {
					s.logger.Warn().Err(err).Str("executor_id", executorID).Msg("persist executor disconnect failed")
				}
			}
		}
		event := s.logger.Info().Str("peer", peerAddr)
		if executorID != "" {
			event = event.Str("executor_id", executorID)
		}
		if retErr != nil {
			event.Err(retErr).Msg("runtime stream disconnected")
			return
		}
		event.Msg("runtime stream disconnected")
	}()

	incoming := make(chan *runtimecontrolv1.RuntimeMessage, 64)
	readErr := make(chan error, 1)
	go func() {
		for {
			message, err := stream.Recv()
			if err != nil {
				readErr <- err
				return
			}
			incoming <- message
		}
	}()

	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case err := <-readErr:
			if err == io.EOF {
				return nil
			}
			return err
		case message := <-incoming:
			response, nextExecutorID, err := s.handleIncoming(message, executorID)
			if err != nil {
				return err
			}
			if nextExecutorID != "" {
				executorID = nextExecutorID
			}
			if response != nil {
				if err := stream.Send(response); err != nil {
					return err
				}
			}
		case <-ticker.C:
			if executorID == "" {
				continue
			}
			outgoing := s.dispatcher.PullOutgoing(executorID, 5*time.Millisecond)
			if outgoing == nil {
				continue
			}
			if err := stream.Send(outgoing); err != nil {
				return err
			}
		}
	}
}

func streamPeerAddr(ctx context.Context) string {
	peerInfo, ok := peer.FromContext(ctx)
	if !ok || peerInfo.Addr == nil {
		return ""
	}
	return peerInfo.Addr.String()
}

func (s *Server) handleIncoming(
	message *runtimecontrolv1.RuntimeMessage,
	currentExecutorID string,
) (*runtimecontrolv1.RuntimeMessage, string, error) {
	switch payload := message.GetPayload().(type) {
	case *runtimecontrolv1.RuntimeMessage_Register:
		register := payload.Register
		session, err := s.dispatcher.RegisterExecutor(register)
		if err != nil {
			return buildError("invalid_register", err.Error(), register.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED), "", nil
		}
		if s.controlPlane != nil {
			if err := s.controlPlane.OnExecutorRegister(context.Background(), register); err != nil {
				s.logger.Warn().Err(err).Str("executor_id", session.ExecutorID).Msg("persist executor register failed")
			}
		}
		s.logger.Info().Str("executor_id", session.ExecutorID).Msg("runtime executor registered")
		return buildAck(
			register.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REGISTER,
			runtimecontrolv1.AckReason_ACK_REASON_REGISTERED,
			"registered",
		), session.ExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_Heartbeat:
		heartbeat := payload.Heartbeat
		executorID := strings.TrimSpace(heartbeat.GetExecutorId())
		if executorID == "" {
			return buildError("invalid_heartbeat", "executor_id is required", heartbeat.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED), "", nil
		}
		if currentExecutorID != "" && currentExecutorID != executorID {
			return buildError("executor_id_conflict", "heartbeat executor_id mismatch", heartbeat.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED), "", nil
		}
		if err := s.dispatcher.HandleHeartbeat(heartbeat); err != nil {
			return buildError("invalid_heartbeat", err.Error(), heartbeat.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED), "", nil
		}
		if s.controlPlane != nil {
			if err := s.controlPlane.OnExecutorHeartbeat(context.Background(), heartbeat); err != nil {
				s.logger.Warn().Err(err).Str("executor_id", executorID).Msg("persist executor heartbeat failed")
			}
		}
		return buildAck(
			heartbeat.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REQUEST,
			runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
			"heartbeat accepted",
		), executorID, nil

	case *runtimecontrolv1.RuntimeMessage_Ack:
		s.dispatcher.HandleAck(payload.Ack)
		return nil, currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_StepEvent:
		event := payload.StepEvent
		stepID := resolveStepID(event.GetStepId())
		if s.controlPlane != nil {
			if err := s.controlPlane.OnStepEvent(context.Background(), event); err != nil {
				s.logger.Warn().Err(err).Str("step_id", stepID).Msg("persist step_event failed")
			}
		}
		return buildAck(
			event.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REQUEST,
			runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
			"step_event accepted",
		), currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_StepResult:
		result := payload.StepResult
		stepID := resolveStepID(result.GetStepId())
		if s.controlPlane != nil {
			if err := s.controlPlane.OnStepResult(context.Background(), result); err != nil {
				s.logger.Warn().Err(err).Str("step_id", stepID).Msg("persist step_result failed")
			}
		}
		return buildAck(
			result.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REQUEST,
			runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
			"step_result accepted",
		), currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_DataRequest:
		request := payload.DataRequest
		stepID := resolveStepID(request.GetStepId())
		if s.domainClient == nil || !s.domainClient.Enabled() {
			return buildError(
				"not_implemented",
				"runtime_domain QueryData is not configured",
				request.GetRequestId(),
				stepID,
				request.GetQueryType(),
			), currentExecutorID, nil
		}
		response, err := s.domainClient.QueryData(context.Background(), &runtimedomainv1.DataRequest{
			RequestId: request.GetRequestId(),
			StepId:    stepID,
			QueryType: toDomainQueryType(request.GetQueryType()),
			ProjectId: request.GetProjectId(),
			CommitId:  request.GetCommitId(),
			Cursor:    request.GetCursor(),
			Limit:     request.GetLimit(),
		})
		if err != nil {
			s.logger.Warn().
				Err(err).
				Str("step_id", stepID).
				Str("request_id", request.GetRequestId()).
				Msg("runtime domain QueryData failed")
			return buildError(
				"data_query_failed",
				"data query failed",
				request.GetRequestId(),
				stepID,
				request.GetQueryType(),
			), currentExecutorID, nil
		}
		return &runtimecontrolv1.RuntimeMessage{
			Payload: &runtimecontrolv1.RuntimeMessage_DataResponse{
				DataResponse: toRuntimeDataResponse(response),
			},
		}, currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_UploadTicketRequest:
		request := payload.UploadTicketRequest
		stepID := resolveStepID(request.GetStepId())
		if s.domainClient == nil || !s.domainClient.Enabled() {
			return buildError(
				"not_implemented",
				"runtime_domain CreateUploadTicket is not configured",
				request.GetRequestId(),
				stepID,
				runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED,
			), currentExecutorID, nil
		}
		response, err := s.domainClient.CreateUploadTicket(context.Background(), &runtimedomainv1.UploadTicketRequest{
			RequestId:    request.GetRequestId(),
			StepId:       stepID,
			ArtifactName: request.GetArtifactName(),
			ContentType:  request.GetContentType(),
		})
		if err != nil {
			s.logger.Warn().
				Err(err).
				Str("step_id", stepID).
				Str("request_id", request.GetRequestId()).
				Msg("runtime domain CreateUploadTicket failed")
			return buildError(
				"upload_ticket_failed",
				"upload ticket failed",
				request.GetRequestId(),
				stepID,
				runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED,
			), currentExecutorID, nil
		}
		respStepID := resolveStepID(response.GetStepId())
		return &runtimecontrolv1.RuntimeMessage{
			Payload: &runtimecontrolv1.RuntimeMessage_UploadTicketResponse{
				UploadTicketResponse: &runtimecontrolv1.UploadTicketResponse{
					RequestId:  response.GetRequestId(),
					ReplyTo:    response.GetReplyTo(),
					StepId:     respStepID,
					UploadUrl:  response.GetUploadUrl(),
					StorageUri: response.GetStorageUri(),
					Headers:    response.GetHeaders(),
				},
			},
		}, currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_Error:
		errPayload := payload.Error
		s.logger.Warn().
			Str("request_id", errPayload.GetRequestId()).
			Str("code", errPayload.GetCode()).
			Str("message", errPayload.GetMessage()).
			Msg("runtime error reported by executor")
		return nil, currentExecutorID, nil

	default:
		return buildError(
			"unknown_payload",
			fmt.Sprintf("unsupported payload type: %T", payload),
			"",
			"",
			runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED,
		), currentExecutorID, nil
	}
}

func buildAck(
	ackFor string,
	status runtimecontrolv1.AckStatus,
	ackType runtimecontrolv1.AckType,
	reason runtimecontrolv1.AckReason,
	detail string,
) *runtimecontrolv1.RuntimeMessage {
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_Ack{
			Ack: &runtimecontrolv1.Ack{
				RequestId: uuid.NewString(),
				AckFor:    ackFor,
				Status:    status,
				Type:      ackType,
				Reason:    reason,
				Detail:    detail,
			},
		},
	}
}

func buildError(
	code string,
	message string,
	replyTo string,
	stepID string,
	queryType runtimecontrolv1.RuntimeQueryType,
) *runtimecontrolv1.RuntimeMessage {
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_Error{
			Error: &runtimecontrolv1.Error{
				RequestId: uuid.NewString(),
				Code:      code,
				Message:   message,
				ReplyTo:   replyTo,
				StepId:    stepID,
				QueryType: queryType,
			},
		},
	}
}

func toDomainQueryType(queryType runtimecontrolv1.RuntimeQueryType) runtimedomainv1.RuntimeQueryType {
	switch queryType {
	case runtimecontrolv1.RuntimeQueryType_LABELS:
		return runtimedomainv1.RuntimeQueryType_LABELS
	case runtimecontrolv1.RuntimeQueryType_SAMPLES:
		return runtimedomainv1.RuntimeQueryType_SAMPLES
	case runtimecontrolv1.RuntimeQueryType_ANNOTATIONS:
		return runtimedomainv1.RuntimeQueryType_ANNOTATIONS
	case runtimecontrolv1.RuntimeQueryType_UNLABELED_SAMPLES:
		return runtimedomainv1.RuntimeQueryType_UNLABELED_SAMPLES
	default:
		return runtimedomainv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED
	}
}

func toRuntimeQueryType(queryType runtimedomainv1.RuntimeQueryType) runtimecontrolv1.RuntimeQueryType {
	switch queryType {
	case runtimedomainv1.RuntimeQueryType_LABELS:
		return runtimecontrolv1.RuntimeQueryType_LABELS
	case runtimedomainv1.RuntimeQueryType_SAMPLES:
		return runtimecontrolv1.RuntimeQueryType_SAMPLES
	case runtimedomainv1.RuntimeQueryType_ANNOTATIONS:
		return runtimecontrolv1.RuntimeQueryType_ANNOTATIONS
	case runtimedomainv1.RuntimeQueryType_UNLABELED_SAMPLES:
		return runtimecontrolv1.RuntimeQueryType_UNLABELED_SAMPLES
	default:
		return runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED
	}
}

func toRuntimeDataResponse(response *runtimedomainv1.DataResponse) *runtimecontrolv1.DataResponse {
	if response == nil {
		return &runtimecontrolv1.DataResponse{}
	}
	items := make([]*runtimecontrolv1.DataItem, 0, len(response.GetItems()))
	for _, item := range response.GetItems() {
		items = append(items, toRuntimeDataItem(item))
	}
	return &runtimecontrolv1.DataResponse{
		RequestId:  response.GetRequestId(),
		ReplyTo:    response.GetReplyTo(),
		StepId:     resolveStepID(response.GetStepId()),
		QueryType:  toRuntimeQueryType(response.GetQueryType()),
		Items:      items,
		NextCursor: response.GetNextCursor(),
	}
}

func resolveStepID(stepID string) string {
	return strings.TrimSpace(stepID)
}

func toRuntimeDataItem(item *runtimedomainv1.DataItem) *runtimecontrolv1.DataItem {
	if item == nil {
		return &runtimecontrolv1.DataItem{}
	}
	switch payload := item.GetItem().(type) {
	case *runtimedomainv1.DataItem_LabelItem:
		return &runtimecontrolv1.DataItem{
			Item: &runtimecontrolv1.DataItem_LabelItem{
				LabelItem: &runtimecontrolv1.LabelItem{
					Id:    payload.LabelItem.GetId(),
					Name:  payload.LabelItem.GetName(),
					Color: payload.LabelItem.GetColor(),
				},
			},
		}
	case *runtimedomainv1.DataItem_SampleItem:
		return &runtimecontrolv1.DataItem{
			Item: &runtimecontrolv1.DataItem_SampleItem{
				SampleItem: &runtimecontrolv1.SampleItem{
					Id:          payload.SampleItem.GetId(),
					AssetHash:   payload.SampleItem.GetAssetHash(),
					DownloadUrl: payload.SampleItem.GetDownloadUrl(),
					Width:       payload.SampleItem.GetWidth(),
					Height:      payload.SampleItem.GetHeight(),
					Meta:        cloneStruct(payload.SampleItem.GetMeta()),
				},
			},
		}
	case *runtimedomainv1.DataItem_AnnotationItem:
		return &runtimecontrolv1.DataItem{
			Item: &runtimecontrolv1.DataItem_AnnotationItem{
				AnnotationItem: &runtimecontrolv1.AnnotationItem{
					Id:         payload.AnnotationItem.GetId(),
					SampleId:   payload.AnnotationItem.GetSampleId(),
					CategoryId: payload.AnnotationItem.GetCategoryId(),
					BboxXywh:   payload.AnnotationItem.GetBboxXywh(),
					Obb:        cloneStruct(payload.AnnotationItem.GetObb()),
					Source:     payload.AnnotationItem.GetSource(),
					Confidence: payload.AnnotationItem.GetConfidence(),
				},
			},
		}
	default:
		return &runtimecontrolv1.DataItem{}
	}
}

func cloneStruct(source *structpb.Struct) *structpb.Struct {
	if source == nil {
		return &structpb.Struct{}
	}
	target := &structpb.Struct{}
	target.Fields = map[string]*structpb.Value{}
	for key, value := range source.GetFields() {
		target.Fields[key] = value
	}
	return target
}
