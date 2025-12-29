# Saki API Documentation

Base URL: `/api/v1`

## 1. Authentication & Users

### Login (Get Access Token)
- **Endpoint**: `POST /login/access-token`
- **Content-Type**: `application/x-www-form-urlencoded`
- **Body**:
  - `username`: string (email)
  - `password`: string
- **Response**:
  ```json
  {
    "access_token": "string",
    "token_type": "bearer"
  }
  ```

### Register User
- **Endpoint**: `POST /register`
- **Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "strongpassword",
    "full_name": "John Doe"
  }
  ```
- **Response**: `User` object.

### Get Current User
- **Endpoint**: `GET /users/me` (Note: This endpoint might need to be added to backend if not exists, or use token info)
- **Headers**: `Authorization: Bearer <token>`
- **Response**: `User` object.

## 2. System Configuration (global)

System-level options that every project references. Only admins should mutate these.

### List Query Strategies
- **Endpoint**: `GET /configs/strategies`
- **Response**:
  ```json
  [
    {"id": "least_confidence", "name": "Least Confidence", "description": "Select samples where the model is least confident", "paramsSchema": {"k": {"type": "integer", "default": 10}}, "enabled": true}
  ]
  ```

### Create/Update/Delete Query Strategy
- **Endpoints**:
  - `POST /configs/strategies`
  - `PUT /configs/strategies/{id}`
  - `DELETE /configs/strategies/{id}`
- **Body (POST/PUT)**:
  ```json
  {
    "id": "entropy_sampling",            // slug used by AL engine
    "name": "Entropy Sampling",
    "description": "Highest predictive entropy",
    "entrypoint": "al_engine.strategies.entropy:EntropyStrategy",
    "paramsSchema": {"batchSize": {"type": "integer", "minimum": 1}},
    "enabled": true
  }
  ```

### List Base Models (system-level)
- **Endpoint**: `GET /configs/base-models`
- **Response**:
  ```json
  [
    {"id": "resnet50", "name": "ResNet-50", "taskType": "classification", "framework": "pytorch", "provider": "torchvision", "artifactUri": "", "defaultConfig": {"inputSize": 224}, "enabled": true}
  ]
  ```

### Create/Update/Delete Base Model
- **Endpoints**:
  - `POST /configs/base-models`
  - `PUT /configs/base-models/{id}`
  - `DELETE /configs/base-models/{id}`
- **Body (POST/PUT)**:
  ```json
  {
    "id": "yolov8n",
    "name": "YOLOv8-Nano",
    "taskType": "detection",
    "framework": "pytorch",
    "provider": "ultralytics",
    "artifactUri": "s3://models/yolov8n.pt", // or HF model id
    "defaultConfig": {"imgsz": 640},
    "description": "Default YOLOv8 nano weights",
    "enabled": true
  }
  ```

## 3. Project Management

### List Projects
- **Endpoint**: `GET /projects`
- **Description**: Retrieve a list of all projects.
- **Response**:
  ```json
  [
    {
      "id": "string",
      "name": "string",
      "description": "string",
      "taskType": "classification" | "detection",
      "createdAt": "string (ISO8601)",
      "stats": {
        "totalSamples": number,
        "labeledSamples": number,
        "accuracy": number
      }
    }
  ]
  ```

### Create Project
- **Endpoint**: `POST /projects`
- **Body**:
  ```json
  {
    "name": "string",
    "description": "string",
    "taskType": "classification" | "detection",
  "queryStrategyId": "least_confidence",          // reference to system strategy
  "baseModelId": "resnet50",                      // reference to system base model
    "labels": [
        { "name": "string", "color": "string" }
    ],
    "alConfig": {
        "batchSize": number
    },
  "modelConfig": {
    "extra": "per-project overrides for the base model"
  }
  }
  ```
- **Response**: `Project` object.

### Get Project Details
- **Endpoint**: `GET /projects/{id}`
- **Response**: `Project` object.

### Update Project
- **Endpoint**: `PUT /projects/{id}`
- **Body**: Partial `Project` object.
- **Response**: Updated `Project` object.

### Delete Project
- **Endpoint**: `DELETE /projects/{id}`
- **Response**: `204 No Content`

## 4. Data Management

### List Samples
- **Endpoint**: `GET /projects/{projectId}/samples`
- **Query Params**:
  - `status`: "labeled" | "unlabeled" | "skipped" (optional)
  - `page`: number
  - `limit`: number
- **Response**:
  ```json
  {
    "items": [
      {
        "id": "string",
        "projectId": "string",
        "url": "string", // URL to fetch the image
        "status": "labeled" | "unlabeled" | "skipped",
        "score": number // Informativeness score
      }
    ],
    "total": number
  }
  ```

### Upload Samples
- **Endpoint**: `POST /projects/{projectId}/samples`
- **Content-Type**: `multipart/form-data`
- **Body**:
  - `files`: File[]
- **Response**:
  ```json
  {
    "uploaded": number,
    "errors": number
  }
  ```

### Get Sample Image
- **Endpoint**: `GET /samples/{id}/image`
- **Description**: Returns the raw image file.

## 5. Annotation

### Get Annotation
## 5. Annotations (Real-time Sync & Batch Save)

The annotation system supports two workflows:
1. **Real-time Sync**: Each create/update/delete action is synced to the backend for processing (especially for FEDO dual-view mapping)
2. **Batch Save**: All annotations are persisted when user clicks "Save"

### Get Sample Annotations
- **Endpoint**: `GET /annotations/{sampleId}`
- **Response**:
  ```json
  {
    "sample_id": "string",
    "dataset_id": "string",
    "annotation_system": "classic" | "fedo",
    "annotations": [
      {
        "id": "string",
        "type": "rect" | "obb" | "polygon" | "polyline" | "point",
        "source": "manual" | "auto" | "imported",
        "label_id": "string",
        "label_name": "string",
        "label_color": "#1890ff",
        "parent_id": "string | null",
        "view": "time-energy" | "L-omegad" | null,
        "data": {
          "x": 100, "y": 100, "width": 50, "height": 30, "rotation": 0
        }
      }
    ]
  }
  ```

### Sync Annotation Actions (Real-time)
- **Endpoint**: `POST /annotations/sync`
- **Description**: Sync annotation actions during annotation session. Does NOT persist to database. For FEDO, returns auto-generated linked annotations.
- **Body**:
  ```json
  {
    "sample_id": "string",
    "actions": [
      {
        "action": "create" | "update" | "delete",
        "annotation_id": "string",
        "label_id": "string",
        "type": "obb",
        "view": "time-energy",
        "data": {"x": 100, "y": 100, "width": 50, "height": 30, "rotation": 0}
      }
    ]
  }
  ```
- **Response**:
  ```json
  {
    "sample_id": "string",
    "results": [
      {
        "action": "create",
        "annotation_id": "string",
        "success": true,
        "error": null,
        "generated": [
          {
            "id": "auto-gen-id",
            "type": "obb",
            "source": "auto",
            "label_id": "string",
            "parent_id": "original-annotation-id",
            "view": "L-omegad",
            "data": {"x": 80, "y": 60, "width": 25, "height": 21, "rotation": 15}
          }
        ]
      }
    ],
    "ready": true
  }
  ```

### Batch Save Annotations
- **Endpoint**: `POST /annotations/save`
- **Description**: Persist all annotations to database. Called when user clicks "Save".
- **Body**:
  ```json
  {
    "sample_id": "string",
    "annotations": [
      {
        "id": "string",
        "type": "obb",
        "source": "manual",
        "label_id": "string",
        "parent_id": null,
        "view": "time-energy",
        "data": {"x": 100, "y": 100, "width": 50, "height": 30, "rotation": 0}
      },
      {
        "id": "auto-gen-id",
        "type": "obb",
        "source": "auto",
        "label_id": "string",
        "parent_id": "manual-annotation-id",
        "view": "L-omegad",
        "data": {"x": 80, "y": 60, "width": 25, "height": 21, "rotation": 15}
      }
    ],
    "update_status": "labeled" | "skipped" | null
  }
  ```
- **Response**:
  ```json
  {
    "sample_id": "string",
    "saved_count": 2,
    "success": true,
    "error": null
  }
  ```

### Delete All Sample Annotations
- **Endpoint**: `DELETE /annotations/{sampleId}`
- **Response**:
  ```json
  {
    "deleted": 5,
    "sample_id": "string"
  }
  ```

### Get Child Annotations (FEDO linked annotations)
- **Endpoint**: `GET /annotations/children/{parentId}`
- **Response**: Array of `AnnotationItem` objects linked to the parent.

### Annotation Data Types

| Type | Data Format |
|------|-------------|
| `rect` | `{x, y, width, height}` |
| `obb` | `{x, y, width, height, rotation}` (rotation in degrees) |
| `polygon` | `{points: [[x1,y1], [x2,y2], ...]}` |
| `polyline` | `{points: [[x1,y1], [x2,y2], ...]}` |
| `point` | `{x, y}` |

### FEDO Dual-View Annotation Flow

1. User creates annotation in `time-energy` or `L-omegad` view
2. Frontend calls `POST /annotations/sync` with the create action
3. Backend processes the annotation through `FedoAnnotationProcessor`
4. Backend returns auto-generated mapped annotations for the other view
5. Frontend displays both manual and auto-generated annotations
6. User can continue editing (each edit triggers sync)
7. User clicks "Save" → `POST /annotations/save` persists all annotations
8. Manual annotations have `source: "manual"`, auto-generated have `source: "auto"` with `parent_id` linking to the manual annotation


## 6. Active Learning & Models

### Trigger Training
- **Endpoint**: `POST /projects/{projectId}/train`
- **Description**: Start training the model on currently labeled data.
- **Response**:
  ```json
  {
    "jobId": "string",
    "status": "queued",
    "modelVersion": {
      "id": "string",
      "projectId": "string",
      "baseModelId": "string",
      "name": "v1",
      "status": "training"
    }
  }
  ```

### Get Training Status/Metrics
- **Endpoint**: `GET /projects/{projectId}/train/status`
- **Response**:
  ```json
  {
    "status": "training" | "completed" | "failed",
    "progress": number,
    "currentMetrics": {
        "accuracy": number,
        "loss": number
    },
    "history": [ ... ]
  }
  ```

### Query Next Batch (AL Step)
- **Endpoint**: `POST /projects/{projectId}/query`
- **Description**: Calculate scores for unlabeled samples and return the most informative ones.
- **Body**:
  ```json
  {
    "n": number // Number of samples to query
  }
  ```
- **Response**: List of `Sample` objects.

### List Project Model Versions
- **Endpoint**: `GET /projects/{projectId}/models`
- **Response**:
  ```json
  [
    {
      "id": "string",
      "name": "v1",
      "baseModelId": "resnet50",
      "status": "ready",
      "metrics": {"accuracy": 0.92},
      "createdAt": "string"
    }
  ]
  ```

### Register/Update a Model Version
- **Endpoint**: `POST /projects/{projectId}/models`
- **Body**:
  ```json
  {
    "name": "v2",
    "baseModelId": "resnet50",
    "metrics": {"map50": 0.41},
    "pathToWeights": "s3://.../v2.pt",
    "config": {"epochs": 50},
    "status": "ready"
  }
  ```
- **Endpoint (update)**: `PUT /projects/{projectId}/models/{modelId}` (partial body)
