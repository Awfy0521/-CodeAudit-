import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import settings

Base = declarative_base()


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(Text, nullable=False)
    source = Column(String(20), nullable=False, default="local")  # github_full / github_path / local
    scope = Column(String(20), nullable=False, default="full")
    target_path = Column(String(500), nullable=True)
    repo_url = Column(String(1000), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    reports = relationship("ReviewReport", back_populates="task", cascade="all, delete-orphan")


class ReviewReport(Base):
    __tablename__ = "review_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("review_tasks.id"), nullable=False)
    review_type = Column(String(20), nullable=False)  # security / perf / business / merged
    findings = Column(Text, nullable=True)  # JSON string
    severity_summary = Column(Text, nullable=True)  # JSON string
    fixed_code = Column(Text, nullable=True)
    diff = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    task = relationship("ReviewTask", back_populates="reports")


engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    Base.metadata.create_all(bind=engine)
