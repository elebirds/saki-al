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
- **Endpoint**: `GET /samples/{sampleId}/annotation`
- **Response**:
  ```json
  {
    "id": "string",
    "sampleId": "string",
    "data": {
        // Task specific data
        // Detection: list of bboxes
        // Classification: classId
    },
    "annotatorId": "string"
  }
  ```

### Save Annotation
- **Endpoint**: `POST /samples/{sampleId}/annotation`
- **Body**:
  ```json
  {
    "data": object,
    "status": "labeled" | "skipped"
  }
  ```
- **Response**: `Annotation` object.

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
