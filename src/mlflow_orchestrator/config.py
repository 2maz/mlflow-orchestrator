from __future__ import annotations

from pathlib import Path
import yaml
import subprocess
from pydantic import BaseModel
from pydantic_settings import BaseSettings

import logging
import boto3
from logging import getLogger

logger = getLogger(__name__)
logger.setLevel(logging.INFO)


class MLFlowAuth(BaseModel):
    auth_type: str
    default_permission: str = "READ_PERMISSIONS"
    database_uri: str | None = "basic_auth.db"
    admin_username: str = "admin"
    admin_password: str = "password"
    # authorization_function: str = "mlflow.server.auth:authenticate_request_basic_auth"


class MLFlowEnvironment(BaseModel):
    # https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html#using-a-configuration-file
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_CONFIG_FILE: str | None = None

    MLFLOW_S3_ENDPOINT_URL: str | None = None
    MLFLOW_S3_IGNORE_TLS: bool = True


class MLFlowArtifacts(BaseModel):
    serve: bool = False
    destination: str | None = None


class MLFlowInstance(BaseSettings):
    class Config:
        arbitrary_types_allowed = True

    auth: MLFlowAuth | None = None

    name: str
    host_name: str = "0.0.0.0"
    port: int | None = None

    badge_prefix: str = "id"
    badge_color: str = "orange"

    artifacts: MLFlowArtifacts = MLFlowArtifacts()
    environment: MLFlowEnvironment = MLFlowEnvironment()

    # Runtime management only
    process: subprocess.CompletedProcess | None = None

    @classmethod
    def from_yaml(cls, filename: str | Path) -> MLFlowInstance:
        with open(filename, "r") as f:
            data = yaml.safe_load(f)
            return cls(**data)

    def prepare(self, hostname):
        for k, v in dict(self.environment).items():
            if v is not None:
                if type(v) == str and v.startswith("http"):
                    setattr(self.environment, str(k), v.replace("hostname", hostname))

        if self.artifacts.destination and self.artifacts.destination.startswith(
            "s3://"
        ):
            self.ensure_s3_bucket()

    def ensure_s3_bucket(self, name: str | None = None, region: str = "eu-north-1"):
        if self.environment.MLFLOW_S3_ENDPOINT_URL is None:
            raise ValueError("MLFlowInstance: no known S3 endpoint")

        if name is None:
            # Get desired name or use default name
            if self.artifacts.destination.startswith("s3://"):
                name = self.artifacts.destination.replace("s3://", "").replace("/", "")
            else:
                name = self.name

        # Connect to s3 storage
        s3_client = boto3.client(
            service_name="s3",
            endpoint_url=self.environment.MLFLOW_S3_ENDPOINT_URL,
            aws_access_key_id=self.environment.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.environment.AWS_SECRET_ACCESS_KEY,
        )

        response = s3_client.list_buckets()
        for bucket in response["Buckets"]:
            if bucket["Name"] == name:
                logger.info(f"Bucket '{name}' already exists")
                return

        logger.info(f"Create bucket '{name}'")
        location = {"LocationConstraint": region}
        s3_client.create_bucket(Bucket=name, CreateBucketConfiguration=location)

        if self.artifacts.serve and self.artifacts.destination is None:
            self.artifacts.destination = f"s3://{name}"
