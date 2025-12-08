# Saki - Visual Active Learning Framework Design Document

## 1. System Overview
Saki is a full-stack Active Learning (AL) platform designed for computer vision tasks (Classification, Object Detection). It aims to reduce annotation costs by intelligently selecting the most informative samples for human labeling.

### Core Philosophy
- **Model-Agnostic**: Supports PyTorch, TensorFlow, etc., via a unified adapter interface.
- **Interactive**: Real-time feedback loop between annotation and model training.
- **Extensible**: Plugin system for new AL strategies and model architectures.

## 2. Architecture

```mermaid
graph TD
    User[User / Annotator] -->|Web Interface| Frontend[React + TS Frontend]
    Frontend -->|REST API| Backend[FastAPI Backend]
    
    subgraph "Backend Services"
        Backend --> ProjectMgr[Project Manager]
        Backend --> DataMgr[Data Manager]
        Backend --> ALMgr[Active Learning Engine]
    end
    
    subgraph "Storage"
        DataMgr --> DB[(SQLite/PostgreSQL)]
        DataMgr --> FileStore[File System (Images/Models)]
    end
    
    subgraph "Compute / ML"
        ALMgr --> Strategy[Query Strategies (Entropy, Margin...)]
        ALMgr --> ModelAdapter[Model Adapter Interface]
        ModelAdapter --> DLFramework[PyTorch / TensorFlow]
    end
```

## 3. Tech Stack

### Frontend (`saki-web`)
- **Framework**: React 18
- **Language**: TypeScript
- **State Management**: Zustand or Redux Toolkit
- **UI Library**: Ant Design or Material UI
- **Canvas/Annotation**: `react-konva` or `fabric.js` for bounding boxes/polygons.
- **Charts**: Recharts (for training metrics).

### Backend (`saki-api`)
- **Framework**: FastAPI (Python 3.9+)
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Task Queue**: Celery + Redis (for long-running training tasks) - *Optional for MVP, can use BackgroundTasks initially.*
- **Image Processing**: Pillow, OpenCV.

### Active Learning Core (`saki-core`)
- **AL Framework**: `modAL` (modular Active Learning framework for Python) or custom implementation of common strategies.
- **DL Support**: PyTorch (primary support), extensible to others.
- **Strategies**:
  - Uncertainty Sampling (Least Confidence, Margin, Entropy)
  - Diversity Sampling (K-Means based)
  - Query-by-Committee (QBC)

## 4. Data Model (Simplified)

- **Project**: `id`, `name`, `task_type` (classification/detection), `created_at`
- **Dataset**: `id`, `project_id`, `name`
- **Sample**: `id`, `dataset_id`, `file_path`, `status` (unlabeled, labeled, skipped)
- **Annotation**: `id`, `sample_id`, `data` (JSON: class_id, bbox, polygon), `annotator_id`
- **ModelVersion**: `id`, `project_id`, `metrics` (accuracy, mAP), `path_to_weights`

## 5. API Design

### Project Management
- `GET /projects`: List all projects.
- `POST /projects`: Create a new project.
- `GET /projects/{id}`: Get project details.

### Data Management
- `POST /projects/{id}/upload`: Upload images.
- `GET /projects/{id}/samples`: List samples (filter by status).
- `GET /samples/{id}/image`: Serve image file.

### Annotation
- `POST /samples/{id}/annotate`: Submit annotation.
- `GET /samples/{id}/annotation`: Get existing annotation.

### Active Learning Loop
- `POST /projects/{id}/train`: Trigger a training cycle (Train on labeled pool).
- `POST /projects/{id}/query`: Request next batch of samples to label (AL Query).
  - Returns list of `sample_id` sorted by informativeness.
- `GET /projects/{id}/metrics`: Get model performance history.

## 6. Workflow

1.  **Initialization**: User creates a project and uploads a pool of unlabeled images.
2.  **Cold Start**: 
    - Option A: Randomly sample N images for initial labeling.
    - Option B: Use a pre-trained model to extract features and cluster.
3.  **Annotation**: User labels the selected samples in the UI.
4.  **Training**: System trains a model on the labeled set.
5.  **Query (AL Step)**: 
    - The trained model predicts on the remaining unlabeled pool.
    - An acquisition function (e.g., Entropy) calculates an "informativeness" score for each sample.
    - The top K samples are presented to the user for labeling.
6.  **Loop**: Repeat steps 3-5 until performance target is met or budget is exhausted.

## 7. Directory Structure

```
saki/
├── saki-web/           # Frontend
│   ├── src/
│   │   ├── components/ # UI Components
│   │   ├── pages/      # Route Pages
│   │   ├── services/   # API Client
│   │   └── types/      # TS Interfaces
├── saki-api/           # Backend
│   ├── app/
│   │   ├── api/        # Endpoints
│   │   ├── core/       # Config, Security
│   │   ├── models/     # DB Models
│   │   ├── schemas/    # Pydantic Schemas
│   │   └── services/   # Business Logic
│   ├── al_engine/      # Active Learning Logic
│   │   ├── strategies/ # Entropy, Margin, etc.
│   │   └── wrappers/   # PyTorch/TF Wrappers
│   └── main.py
├── data/               # Local storage for uploaded files
└── DESIGN.md
```
