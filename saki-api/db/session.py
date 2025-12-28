from sqlmodel import create_engine, Session, SQLModel
from core.config import settings

# SQLite requires specific connection arguments to work with multi-threaded applications
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Create the database engine
engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=connect_args)

def get_session():
    """
    Dependency function to get a database session.
    Yields a Session object that is closed after use.
    """
    with Session(engine) as session:
        yield session

def init_db():
    """
    Initialize the database by creating all tables defined in SQLModel metadata.
    This should be called on application startup.
    """
    # Import models to ensure they are registered with SQLModel
    import models
    SQLModel.metadata.create_all(engine)
