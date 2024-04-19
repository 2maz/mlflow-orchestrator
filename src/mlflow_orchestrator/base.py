#!/usr/bin/env python3

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import yaml
import subprocess
import os
import sys
import time

import importlib

if not hasattr(importlib, "resources"):
    import importlib_resources

    setattr(importlib, "resources", importlib_resources)

from mlflow_orchestrator.config import MLFlowInstance

import logging
from logging import getLogger

logger = getLogger(__name__)
logger.setLevel(logging.INFO)


class MLFlowOrchestrator:
    _instances: dict[str, MLFlowInstance]
    base_dir: Path

    def __init__(self, config_dir: str | Path, base_dir: str | Path, host_name: str):
        config_dir = Path(config_dir)
        if not config_dir.exists() or not list(config_dir.glob("*.yaml")):
            logger.info("conf.d dir does not exist: creating default")
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(config_dir / "default.yaml", "w") as f:
                f.write("name: default")

        self._instances = self.load_confd(config_dir)
        self.base_dir = Path(base_dir)
        self.host_name = host_name

    @property
    def log_dir(self) -> Path:
        log_dir = self.base_dir / "server-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def start_instance(self, name: str):
        instance = self._instances[name]
        instance.prepare(hostname=self.host_name)

        logfile_name = self.log_dir / f"{instance.name}.log"
        logfile = open(logfile_name, "w+")

        cmd = [
            "mlflow",
            "server",
            "--port",
            str(instance.port),
            "--host",
            "0.0.0.0",
            "--static-prefix",
            f"/{instance.name}",
            "--backend-store-uri",
            f"file://{self.base_dir}/mlflow-data/{instance.name}/mlruns",
        ]
        env = os.environ.copy()

        if instance.auth is not None:
            if instance.auth.auth_type == "basic-auth":
                cmd.extend(["--app-name", "basic-auth"])
                auth_config = dict(instance.auth)
                del auth_config["auth_type"]

                auth_config_ini = Path(
                    f"{self.base_dir}/instances/{instance.name}/auth_config.ini"
                )
                auth_config_ini.parent.mkdir(parents=True, exist_ok=True)

                db_path = Path(
                    f"{self.base_dir}/instances/{instance.name}/basic_auth.db"
                )
                with open(auth_config_ini, "w") as f:
                    f.write("[mlflow]\n")
                    auth_config["database_uri"] = f"sqlite:///{db_path}"

                    for k, v in auth_config.items():
                        f.write(f"{k} = {v}\n")

                env["MLFLOW_AUTH_CONFIG_PATH"] = auth_config_ini

        if instance.artifacts is not None:
            if instance.artifacts.serve is True:
                cmd.extend(["--serve-artifacts"])
            if instance.artifacts.destination is not None:
                cmd.extend(["--artifacts-destination", instance.artifacts.destination])

        for k, v in dict(instance.environment).items():
            if v is not None:
                if type(v) == bool:
                    v = str(v).lower()

                env[k] = v

        logger.info(f"Starting: {cmd} - (see {logfile_name})")
        logger.debug(f"Using env: {env}")
        process = subprocess.Popen(
            cmd, stdout=logfile, stderr=subprocess.STDOUT, env=env
        )

        self.register(name, process)

    def register(self, name: str, process):
        self._instances[name].process = process

    def run(self):
        [self.start_instance(name=k) for k in self._instances]

    def wait_for_running(self, delay_in_s: int = 1, show: bool = True):
        txt = []
        while True:
            running_instances = []
            if txt:
                print(f"\033[{len(txt)}A", end="")

            txt = ["\nActive instances:"]
            for name, instance in self._instances.items():
                if instance.process.poll() is None:
                    txt.append(f"    {instance.name} - listening on: {instance.port}")
                    running_instances.append(instance.name)
            txt.append("Press CTRL+C to stop all running")
            sys.stdout.write("\n".join(txt))
            if not running_instances:
                break

            time.sleep(delay_in_s)

    def terminate(self):
        logger.info("Shutting down ...")
        [instance.process.terminate() for _, instance in self._instances.items()]

    def generate_nginx_instance_conf(
        self, template_path: Path = None, port_start_range: int = 10000
    ):
        if template_path is None:
            template_path = (
                importlib.resources.files("mlflow_orchestrator").joinpath("templates")
                / "nginx"
            )

        environment = Environment(loader=FileSystemLoader(searchpath=template_path))
        mlflow_instance_template = environment.get_template(
            "mlflow-instance.conf.template"
        )

        output_dir = self.base_dir / "nginx" / "mlflow-instances"
        output_dir.mkdir(parents=True, exist_ok=True)

        port_mapping = {}
        port_mapping_yaml = output_dir / "port_mapping.yaml"
        if port_mapping_yaml.exists():
            with open(port_mapping_yaml, "r") as f:
                data = yaml.safe_load(f)
                if data is not None:
                    port_mapping = data

        port_mapping["__default__"] = port_start_range

        instances = []
        for name, instance in self._instances.items():
            filename = output_dir / f"{name}.conf"
            if instance.name in port_mapping:
                instance.port = port_mapping[instance.name]
            else:
                instance.port = max(port_mapping.values()) + 1
                port_mapping[instance.name] = instance.port

            instances.append({"name": instance.name})

            with open(filename, "w") as f:
                content = mlflow_instance_template.render(
                    host_name=self.host_name,
                    name=instance.name,
                    port=instance.port,
                    badge=f"{instance.badge_prefix}-{instance.name.replace('-','_')}-{instance.badge_color}",
                )
                f.write(content)

        (output_dir / "www").mkdir(parents=True, exist_ok=True)
        index_html_template = environment.get_template("index.html.template")

        index_html_content = index_html_template.render(instances=instances)
        index_html_filename = output_dir / "www" / "index.html"
        with open(index_html_filename, "w") as f:
            f.write(index_html_content)

        # write port_mapping
        with open(port_mapping_yaml, "w") as f:
            yaml.dump(port_mapping, f)

    @staticmethod
    def load_confd(directory: str | Path) -> dict[str, MLFlowInstance]:
        filenames = sorted(Path(directory).glob("*.yaml"))

        instances = {}
        for file in filenames:
            instance = MLFlowInstance.from_yaml(file)
            instances[instance.name] = instance

        return instances
