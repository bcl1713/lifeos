from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TaskList(Base):
    __tablename__ = "task_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="task_list")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    outcome: Mapped[Optional[str]] = mapped_column(Text)
    baseline: Mapped[Optional[str]] = mapped_column(Text)
    target: Mapped[Optional[str]] = mapped_column(Text)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    constraints: Mapped[Optional[str]] = mapped_column(Text)
    review_cadence: Mapped[Optional[str]] = mapped_column(String(100))
    review_date: Mapped[Optional[date]] = mapped_column(Date)
    adjustment_trigger: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    projects: Mapped[list["Project"]] = relationship(back_populates="goal")
    routines: Mapped[list["Routine"]] = relationship(back_populates="goal")
    tasks: Mapped[list["Task"]] = relationship(back_populates="goal")
    milestones: Mapped[list["GoalMilestone"]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class GoalMilestone(Base):
    __tablename__ = "goal_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    goal: Mapped[Goal] = relationship(back_populates="milestones")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    owner: Mapped[Optional[str]] = mapped_column(String(200))
    collaborators: Mapped[Optional[str]] = mapped_column(Text)
    scope: Mapped[Optional[str]] = mapped_column(Text)
    non_goals: Mapped[Optional[str]] = mapped_column(Text)
    risks: Mapped[Optional[str]] = mapped_column(Text)
    deadline: Mapped[Optional[date]] = mapped_column(Date)
    review_trigger: Mapped[Optional[str]] = mapped_column(Text)
    source_refs: Mapped[Optional[str]] = mapped_column(Text)
    goal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    goal: Mapped[Optional[Goal]] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")


class Routine(Base):
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    cadence: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False)
    minimum_occurrences: Mapped[Optional[int]] = mapped_column(Integer)
    frequency_window_days: Mapped[Optional[int]] = mapped_column(Integer)
    task_list_id: Mapped[int] = mapped_column(ForeignKey("task_lists.id", ondelete="CASCADE"), nullable=False)
    goal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    goal: Mapped[Optional[Goal]] = relationship(back_populates="routines")
    task_list: Mapped[TaskList] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="routine")
    skips: Mapped[list["RoutineSkip"]] = relationship(back_populates="routine", cascade="all, delete-orphan")


class RoutineSkip(Base):
    __tablename__ = "routine_skips"
    __table_args__ = (UniqueConstraint("routine_id", "scheduled_date", name="uq_routine_skip_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id", ondelete="CASCADE"), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    routine: Mapped[Routine] = relationship(back_populates="skips")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(500))
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    task_list_id: Mapped[int] = mapped_column(ForeignKey("task_lists.id", ondelete="CASCADE"), nullable=False)
    goal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    routine_id: Mapped[Optional[int]] = mapped_column(ForeignKey("routines.id", ondelete="SET NULL"))
    occurrence_key: Mapped[Optional[str]] = mapped_column(String(180), unique=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    task_list: Mapped[TaskList] = relationship(back_populates="tasks")
    goal: Mapped[Optional[Goal]] = relationship(back_populates="tasks")
    project: Mapped[Optional[Project]] = relationship(back_populates="tasks")
    routine: Mapped[Optional[Routine]] = relationship(back_populates="tasks")
    parent: Mapped[Optional["Task"]] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Task"]] = relationship(back_populates="parent")


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    depends_on_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(30), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(80))
    aggregation: Mapped[str] = mapped_column(String(30), default="latest", nullable=False)
    display: Mapped[str] = mapped_column(String(30), default="number", nullable=False)
    privacy: Mapped[str] = mapped_column(String(30), default="private", nullable=False)
    missing_policy: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    entries: Mapped[list["MetricEntry"]] = relationship(back_populates="metric", cascade="all, delete-orphan")


class MetricEntry(Base):
    __tablename__ = "metric_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False)
    recorded_on: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(300))
    estimated: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    metric: Mapped[MetricDefinition] = relationship(back_populates="entries")


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
