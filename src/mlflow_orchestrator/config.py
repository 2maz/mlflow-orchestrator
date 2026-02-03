from __future__ import annotations

from enum import Enum
from pathlib import Path
import yaml
import subprocess
import psutil
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
    """
    An MLFlowInstance configuration
    """

    class Status(Enum):
        STOPPED = 0
        RUNNING = 1

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

    # Whether this instance should be started (default False)
    enable: bool = False

    def collect_changes(self, other: MLFlowInstance):
        changes = {}
        for k, v in self.__dict__.items():
            if other.__dict__[k] != v:
                changes[k] = {"from": v, "to": other.__dict__[k]}

        return changes

    @classmethod
    def from_yaml(cls, filename: str | Path) -> MLFlowInstance:
        with open(filename, "r") as f:
            data = yaml.safe_load(f)
            return cls(**data)

    def prepare(self, hostname):
        """
        Prepare environment and storage setups

        Replaces 'hostname' with current ip and
        validates setup as s3 buckets if configured

        """
        for k, v in dict(self.environment).items():
            if v is not None:
                if type(v) is str and v.startswith("http"):
                    setattr(self.environment, str(k), v.replace("hostname", hostname))

        if self.artifacts.destination and self.artifacts.destination.startswith(
            "s3://"
        ):
            self.ensure_s3_bucket()

    def stop(self, timeout: int | None = 20, on_terminate: any = None):
        """
        Ensure that all processes associated with this instance will be terminated
        """
        if self.process is None:
            return

        # https://psutil.readthedocs.io/en/latest/#kill-process-tree
        parent_process = psutil.Process(self.process.pid)
        processes = parent_process.children(recursive=True)
        processes.append(parent_process)

        for p in processes:
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                pass

        gone, alive = psutil.wait_procs(
            processes, timeout=timeout, callback=on_terminate
        )
        for p in alive:
            p.kill()

    def ensure_s3_bucket(self, name: str | None = None, region: str = "eu-north-1"):
        """
        Ensure that an s3 bucket with the given name exists

        MLFLOW_S3_ENDPOINT_URL needs to be defined in the environment.
        """
        if self.environment.MLFLOW_S3_ENDPOINT_URL is None:
            raise ValueError(f"MLFlowInstance '{self.name}': no known S3 endpoint")

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
                logger.debug(f"Bucket '{name}' already exists")
                return

        logger.info(f"MLFlowInstance '{self.name}' - create bucket '{name}'")
        location = {"LocationConstraint": region}
        s3_client.create_bucket(Bucket=name, CreateBucketConfiguration=location)

        if self.artifacts.serve and self.artifacts.destination is None:
            self.artifacts.destination = f"s3://{name}"
