from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from flask_login import UserMixin
from datetime import datetime

engine = create_engine("sqlite:///flowline.db")

class Base(DeclarativeBase):
    pass

class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True)
    business_name = Column(String(200), nullable=False)
    owner_name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    address = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)

    credentials = relationship("ProviderCredentials", back_populates="provider")
    services = relationship("ProviderService", back_populates="provider")
    appointments = relationship("Appointment", back_populates="provider")
    queue_entries = relationship("QueueEntry", back_populates="provider")
    settings = relationship("ProviderSettings", back_populates="provider")
    subscription = relationship("ProviderSubscription", back_populates="provider")
    staff = relationship("ProviderStaff", back_populates="provider")

class ProviderCredentials(Base):
    __tablename__ = "provider_credentials"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider = relationship("Provider", back_populates="credentials")

class ProviderService(Base):
    __tablename__ = "provider_services"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    name = Column(String(100), nullable=False)
    duration_minutes = Column(Integer, nullable=False)

    provider = relationship("Provider", back_populates="services")

class ProviderStaff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    name = Column(String(200), nullable=False)
    is_owner = Column(Boolean, default=False)

    provider = relationship("Provider", back_populates="staff")
    appointments = relationship("Appointment", back_populates="staff_member")
    queue_entries = relationship("QueueEntry", back_populates="staff_member")

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    services_json = Column(String, nullable=True)
    custom_duration = Column(Integer, nullable=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    customer_name = Column(String(200))
    customer_phone = Column(String(50))
    customer_email = Column(String(255))
    start = Column(DateTime(timezone=True), nullable=False)
    end = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    notes = Column(Text)
    status = Column(String(50), default="pending")
    reminded_24h = Column(Boolean, default=False)
    reminded_3h = Column(Boolean, default=False)

    provider = relationship("Provider", back_populates="appointments")
    staff_member = relationship("ProviderStaff", back_populates="appointments")

class QueueEntry(Base):
    __tablename__ = "queue_entries"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    services_json = Column(String, nullable=True)
    custom_duration = Column(Integer, nullable=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    customer_name = Column(String(200))
    customer_phone = Column(String(50))
    start = Column(DateTime(timezone=True))
    end = Column(DateTime(timezone=True))
    duration_minutes = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    original_position = Column(Integer, nullable=False)
    position_with_appointments = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="pending")

    provider = relationship("Provider", back_populates="queue_entries")
    staff_member = relationship("ProviderStaff", back_populates="queue_entries")


class ProviderSettings(Base):
    __tablename__ = "provider_settings"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)

    reminder_24h = Column(Boolean, default=True)
    reminder_3h = Column(Boolean, default=True)

    weekday_open = Column(String, default="06:00")
    weekday_close = Column(String, default="00:00")

    saturday_open = Column(String, default="06:00")
    saturday_close = Column(String, default="00:00")

    sunday_closed = Column(Boolean, default=False)

    queue_enabled = Column(Boolean, default=True)
    queue_max_length = Column(Integer, default=20)

    sms_enabled = Column(Boolean, default=False)

    sms_credits_used = Column(Integer, default=0)
    sms_credits_reset = Column(DateTime, default=datetime.utcnow)

    queue_token = Column(String(64), unique=True, nullable=True)

    provider = relationship("Provider", back_populates="settings")


class ProviderSubscription(Base):
    __tablename__ = "provider_subscriptions"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)

    plan = Column(String(50), nullable=False, default="free")  # free, basic, pro, premium
    start_date = Column(DateTime, nullable=True, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True)
    auto_renew = Column(Boolean, default=True)

    provider = relationship("Provider", back_populates="subscription")



Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

class User(UserMixin):
    def __init__(self, id, email):
        self.id    = id
        self.email = email