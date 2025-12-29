from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime

db = SQLAlchemy()

class AppSetting(db.Model):
    __tablename__ = "app_settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)

class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)  # "immich"
    name = db.Column(db.String(128), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    health_url = db.Column(db.String(512), nullable=False)
    group = db.Column(db.String(128), nullable=True)             # "Media"
    beszel_host = db.Column(db.String(128), nullable=True)       # "arborlon"
    beszel_container = db.Column(db.String(128), nullable=True)  # "immich_server"
    dozzle_container = db.Column(db.String(128), nullable=True)  # defaults to beszel_container
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ServiceSecret(db.Model):
    __tablename__ = "service_secrets"
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), primary_key=True)

    enc_basic_user = db.Column(db.Text, nullable=True)
    enc_basic_pass = db.Column(db.Text, nullable=True)
    enc_headers_json = db.Column(db.Text, nullable=True)  # encrypted JSON string

class CheckResult(db.Model):
    __tablename__ = "check_results"
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), index=True)
    checked_at = db.Column(db.Integer, index=True)  # epoch seconds
    ok = db.Column(db.Boolean, default=False)
    status_code = db.Column(db.Integer, nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, nullable=True)

class MetricsSnapshot(db.Model):
    __tablename__ = "metrics_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), index=True)
    checked_at = db.Column(db.Integer, index=True)

    host_cpu = db.Column(db.Float, nullable=True)
    host_mem_used_bytes = db.Column(db.Float, nullable=True)
    host_mem_total_bytes = db.Column(db.Float, nullable=True)
    host_mem_pct = db.Column(db.Float, nullable=True)

    ctr_cpu = db.Column(db.Float, nullable=True)
    ctr_mem_mb = db.Column(db.Float, nullable=True)  # from Beszel containers.memory (MB)
    ctr_uptime = db.Column(db.String(64), nullable=True)  # "Up 7 days"
    ctr_health = db.Column(db.Integer, nullable=True)

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    active_theme_id = db.Column(db.Integer, db.ForeignKey("themes.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Theme(db.Model):
    __tablename__ = "themes"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(128), nullable=False)
    author = db.Column(db.String(128), nullable=True)
    description = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(8), default="dark")  # light | dark
    tokens_json = db.Column(db.Text, nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
