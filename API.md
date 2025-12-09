# Saki API Documentation

Base URL: `/api/v1`

## 1. Project Management

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
    "labels": [
        { "name": "string", "color": "string" }
    ],
    "alConfig": {
        "strategy": "string",
        "batchSize": number
    },
    "modelConfig": {
        "architecture": "string"
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

## 2. Data Management

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

## 3. Annotation

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

## 4. Active Learning & Models

### Get Available Strategies
- **Endpoint**: `GET /configs/strategies`
- **Response**:
  ```json
  [
    { "id": "string", "name": "string", "description": "string" }
  ]
  ```

### Get Available Architectures
- **Endpoint**: `GET /configs/architectures`
- **Response**:
  ```json
  [
    { "id": "string", "name": "string", "taskType": "string" }
  ]
  ```

### Trigger Training
- **Endpoint**: `POST /projects/{projectId}/train`
- **Description**: Start training the model on currently labeled data.
- **Response**:
  ```json
  {
    "jobId": "string",
    "status": "queued"
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
