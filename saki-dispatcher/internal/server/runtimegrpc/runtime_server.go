package runtimegrpc

import (
	"context"
	"fmt"
	"io"
	"strings"

	"github.com/google/uuid"
	"github.com/rs/zerolog"
	"google.golang.org/grpc/peer"

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
	s.logger.Info().Str("peer", peerAddr).Msg("runtime stream 已连接")

	defer func() {
		if executorID != "" {
			s.dispatcher.UnregisterExecutor(executorID)
			disconnectReason := ""
			if retErr != nil && retErr != io.EOF {
				disconnectReason = retErr.Error()
			}
			if s.controlPlane != nil {
				if err := s.controlPlane.OnExecutorDisconnected(context.Background(), executorID, disconnectReason); err != nil {
					s.logger.Warn().Err(err).Str("executor_id", executorID).Msg("持久化 executor 断连信息失败")
				}
			}
		}
		event := s.logger.Info().Str("peer", peerAddr)
		if executorID != "" {
			event = event.Str("executor_id", executorID)
		}
		if retErr != nil {
			event.Err(retErr).Msg("runtime stream 已断开")
			return
		}
		event.Msg("runtime stream 已断开")
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

	var queueChan <-chan *runtimecontrolv1.RuntimeMessage
	if executorID != "" {
		queueChan = s.dispatcher.GetQueue(executorID)
	}

	for {
		select {
		case err := <-readErr:
			if err == io.EOF {
				return nil
			}
			return err
		case message := <-incoming:
			responses, nextExecutorID, err := s.handleIncoming(message, executorID)
			if err != nil {
				return err
			}
			if nextExecutorID != "" && nextExecutorID != executorID {
				executorID = nextExecutorID
				queueChan = s.dispatcher.GetQueue(executorID)
			}
			for _, response := range responses {
				if response == nil {
					continue
				}
				if err := stream.Send(response); err != nil {
					return err
				}
			}
		case outgoing := <-queueChan:
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
) ([]*runtimecontrolv1.RuntimeMessage, string, error) {
	switch payload := message.GetPayload().(type) {
	case *runtimecontrolv1.RuntimeMessage_Register:
		register := payload.Register
		session, err := s.dispatcher.RegisterExecutor(register)
		if err != nil {
			return singleMessage(buildError("invalid_register", err.Error(), register.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED)), "", nil
		}
		if s.controlPlane != nil {
			if err := s.controlPlane.OnExecutorRegister(context.Background(), register); err != nil {
				s.logger.Warn().Err(err).Str("executor_id", session.ExecutorID).Msg("持久化 executor 注册信息失败")
			}
		}
		s.logger.Info().Str("executor_id", session.ExecutorID).Msg("runtime executor 已注册")
		return singleMessage(buildAck(
			register.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REGISTER,
			runtimecontrolv1.AckReason_ACK_REASON_REGISTERED,
			"已注册",
		)), session.ExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_Heartbeat:
		heartbeat := payload.Heartbeat
		executorID := strings.TrimSpace(heartbeat.GetExecutorId())
		if executorID == "" {
			return singleMessage(buildError("invalid_heartbeat", "executor_id 不能为空", heartbeat.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED)), "", nil
		}
		if currentExecutorID != "" && currentExecutorID != executorID {
			return singleMessage(buildError("executor_id_conflict", "heartbeat executor_id 不一致", heartbeat.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED)), "", nil
		}
		if err := s.dispatcher.HandleHeartbeat(heartbeat); err != nil {
			return singleMessage(buildError("invalid_heartbeat", err.Error(), heartbeat.GetRequestId(), "", runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED)), "", nil
		}
		if s.controlPlane != nil {
			if err := s.controlPlane.OnExecutorHeartbeat(context.Background(), heartbeat); err != nil {
				s.logger.Warn().Err(err).Str("executor_id", executorID).Msg("持久化 executor 心跳失败")
			}
		}
		return singleMessage(buildAck(
			heartbeat.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REQUEST,
			runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
			"心跳已接收",
		)), executorID, nil

	case *runtimecontrolv1.RuntimeMessage_Ack:
		ackContext := s.dispatcher.HandleAck(payload.Ack)
		if s.controlPlane != nil && ackContext != nil {
			if err := s.controlPlane.OnAssignTaskAck(context.Background(), ackContext); err != nil {
				s.logger.Warn().
					Err(err).
					Str("task_id", strings.TrimSpace(ackContext.TaskID)).
					Str("request_id", strings.TrimSpace(ackContext.RequestID)).
					Msg("持久化 assign_task ack 失败")
			}
		}
		return nil, currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_TaskEvent:
		event := payload.TaskEvent
		taskID := resolveTaskID(event.GetTaskId())
		if s.controlPlane != nil {
			if err := s.controlPlane.OnTaskEvent(context.Background(), event); err != nil {
				s.logger.Warn().Err(err).Str("task_id", taskID).Msg("持久化 task_event 失败")
			}
		}
		return singleMessage(buildAck(
			event.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REQUEST,
			runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
			"task_event 已接收",
		)), currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_TaskResult:
		result := payload.TaskResult
		taskID := resolveTaskID(result.GetTaskId())
		if s.controlPlane != nil {
			if err := s.controlPlane.OnTaskResult(context.Background(), result); err != nil {
				s.logger.Warn().Err(err).Str("task_id", taskID).Msg("持久化 task_result 失败")
			}
		}
		return singleMessage(buildAck(
			result.GetRequestId(),
			runtimecontrolv1.AckStatus_OK,
			runtimecontrolv1.AckType_ACK_TYPE_REQUEST,
			runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED,
			"task_result 已接收",
		)), currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_DataRequest:
		request := payload.DataRequest
		taskID := resolveTaskID(request.GetTaskId())
		if s.domainClient == nil || !s.domainClient.Enabled() {
			return singleMessage(buildError(
				"not_implemented",
				"runtime_domain QueryData 未配置",
				request.GetRequestId(),
				taskID,
				request.GetQueryType(),
			)), currentExecutorID, nil
		}
		responses, err := s.domainClient.QueryData(context.Background(), &runtimedomainv1.DataRequest{
			RequestId:            request.GetRequestId(),
			TaskId:               taskID,
			QueryType:            toDomainQueryType(request.GetQueryType()),
			ProjectId:            request.GetProjectId(),
			CommitId:             request.GetCommitId(),
			Cursor:               request.GetCursor(),
			Limit:                request.GetLimit(),
			PreferredChunkBytes:  request.GetPreferredChunkBytes(),
			MaxUncompressedBytes: request.GetMaxUncompressedBytes(),
		})
		if err != nil {
			s.logger.Warn().
				Err(err).
				Str("task_id", taskID).
				Str("request_id", request.GetRequestId()).
				Msg("调用 runtime_domain QueryData 失败")
			return singleMessage(buildError(
				"data_query_failed",
				"数据查询失败",
				request.GetRequestId(),
				taskID,
				request.GetQueryType(),
			)), currentExecutorID, nil
		}
		outgoing := make([]*runtimecontrolv1.RuntimeMessage, 0, len(responses))
		for _, response := range responses {
			outgoing = append(outgoing, &runtimecontrolv1.RuntimeMessage{
				Payload: &runtimecontrolv1.RuntimeMessage_DataResponse{
					DataResponse: toRuntimeDataResponse(response),
				},
			})
		}
		return outgoing, currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_UploadTicketRequest:
		request := payload.UploadTicketRequest
		taskID := resolveTaskID(request.GetTaskId())
		if s.domainClient == nil || !s.domainClient.Enabled() {
			return singleMessage(buildError(
				"not_implemented",
				"runtime_domain CreateUploadTicket 未配置",
				request.GetRequestId(),
				taskID,
				runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED,
			)), currentExecutorID, nil
		}
		response, err := s.domainClient.CreateUploadTicket(context.Background(), &runtimedomainv1.UploadTicketRequest{
			RequestId:    request.GetRequestId(),
			TaskId:       taskID,
			ArtifactName: request.GetArtifactName(),
			ContentType:  request.GetContentType(),
		})
		if err != nil {
			s.logger.Warn().
				Err(err).
				Str("task_id", taskID).
				Str("request_id", request.GetRequestId()).
				Msg("调用 runtime_domain CreateUploadTicket 失败")
			return singleMessage(buildError(
				"upload_ticket_failed",
				"上传凭证创建失败",
				request.GetRequestId(),
				taskID,
				runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED,
			)), currentExecutorID, nil
		}
		respTaskID := resolveTaskID(response.GetTaskId())
		return singleMessage(&runtimecontrolv1.RuntimeMessage{
			Payload: &runtimecontrolv1.RuntimeMessage_UploadTicketResponse{
				UploadTicketResponse: &runtimecontrolv1.UploadTicketResponse{
					RequestId:  response.GetRequestId(),
					ReplyTo:    response.GetReplyTo(),
					TaskId:     respTaskID,
					UploadUrl:  response.GetUploadUrl(),
					StorageUri: response.GetStorageUri(),
					Headers:    response.GetHeaders(),
				},
			},
		}), currentExecutorID, nil

	case *runtimecontrolv1.RuntimeMessage_Error:
		errPayload := payload.Error
		s.logger.Warn().
			Str("request_id", errPayload.GetRequestId()).
			Str("code", errPayload.GetCode()).
			Str("message", errPayload.GetMessage()).
			Msg("executor 上报运行时错误")
		return nil, currentExecutorID, nil

	default:
		return singleMessage(buildError(
			"unknown_payload",
			fmt.Sprintf("不支持的 payload 类型: %T", payload),
			"",
			"",
			runtimecontrolv1.RuntimeQueryType_RUNTIME_QUERY_TYPE_UNSPECIFIED,
		)), currentExecutorID, nil
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
	taskID string,
	queryType runtimecontrolv1.RuntimeQueryType,
) *runtimecontrolv1.RuntimeMessage {
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_Error{
			Error: &runtimecontrolv1.Error{
				RequestId: uuid.NewString(),
				Code:      code,
				Message:   message,
				ReplyTo:   replyTo,
				TaskId:    taskID,
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
	return &runtimecontrolv1.DataResponse{
		RequestId:             response.GetRequestId(),
		ReplyTo:               response.GetReplyTo(),
		TaskId:                resolveTaskID(response.GetTaskId()),
		QueryType:             toRuntimeQueryType(response.GetQueryType()),
		PayloadId:             response.GetPayloadId(),
		ChunkIndex:            response.GetChunkIndex(),
		ChunkCount:            response.GetChunkCount(),
		HeaderProto:           response.GetHeaderProto(),
		PayloadChunk:          response.GetPayloadChunk(),
		PayloadTotalSize:      response.GetPayloadTotalSize(),
		PayloadChecksumCrc32C: response.GetPayloadChecksumCrc32C(),
		ChunkChecksumCrc32C:   response.GetChunkChecksumCrc32C(),
		NextCursor:            response.GetNextCursor(),
		IsLastChunk:           response.GetIsLastChunk(),
	}
}

func resolveTaskID(taskID string) string {
	return strings.TrimSpace(taskID)
}

func singleMessage(message *runtimecontrolv1.RuntimeMessage) []*runtimecontrolv1.RuntimeMessage {
	if message == nil {
		return nil
	}
	return []*runtimecontrolv1.RuntimeMessage{message}
}
