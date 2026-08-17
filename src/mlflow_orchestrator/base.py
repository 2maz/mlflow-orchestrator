#!/usr/bin/env python3

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import yaml
import subprocess
import os
import sys
import time
from threading import Thread
import uuid

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
    config_dir: Path
    port_start_range: int

    _stop: bool = False

    def __init__(
        self,
        config_dir: str | Path,
        base_dir: str | Path,
        host_name: str,
        port_start_range: int = 10000,
    ):
        config_dir = Path(config_dir)
        if not config_dir.exists() or not list(config_dir.glob("*.yaml")):
            logger.info("conf.d dir does not exist: creating default")
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(config_dir / "default.yaml", "w") as f:
                f.write("name: default")

        self._instances = {}
        self.config_dir = config_dir
        self.base_dir = Path(base_dir)
        self.host_name = host_name
        self.port_start_range = port_start_range

    @property
    def log_dir(self) -> Path:
        log_dir = self.base_dir / "server-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def start_instance(self, name: str):
        instance = self._instances[name]

        logfile_name = self.log_dir / f"{instance.name}.log"
        logfile = open(logfile_name, "w+")

        cmd = [
            "mlflow",
            "server",
            "--port",
            str(instance.port),
            "--host",
            str(instance.host_name),
            "--allowed-hosts",
            "*",
            "--cors-allowed-origins",
            "*",
            "--static-prefix",
            f"/{instance.name}",
            "--backend-store-uri",
            f"sqlite:///{self.base_dir}/mlflow-data/{instance.name}/mlruns.db",
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

                env["MLFLOW_FLASK_SERVER_SECRET_KEY"] = f"{instance.name}:{uuid.uuid4()}"
                env["MLFLOW_AUTH_CONFIG_PATH"] = auth_config_ini

        if instance.artifacts is not None:
            if instance.artifacts.serve is True:
                cmd.extend(["--serve-artifacts"])
            if instance.artifacts.destination is not None:
                cmd.extend(["--artifacts-destination", instance.artifacts.destination])

        for k, v in dict(instance.environment).items():
            if v is not None:
                if type(v) is bool:
                    v = str(v).lower()

                env[k] = v

        logger.info(f"Starting: {cmd} - (see {logfile_name})")
        logger.debug(f"Using env: {env}")
        process = subprocess.Popen(
            cmd, stdout=logfile, stderr=subprocess.STDOUT, env=env
        )

        self.register(name, process)

    def stop_instance(self, name):
        if name not in self._instances:
            raise ValueError(f"MLFlowOrchestrator: instance '{name}' is not known")

        if self.get_instance_status(name=name) == MLFlowInstance.Status.STOPPED:
            logger.debug("MLFlowOrchestrator instance '{name}' - already stopped")
            return

        logger.info(f"MLFlowOrchestrator instance '{name}' - stopping")
        self._instances[name].stop()

    def get_instance_status(self, name: str) -> MLFlowInstance.Status:
        if name not in self._instances:
            raise ValueError(f"MLFlowOrchestrator: instance '{name}' is not known")

        instance = self._instances[name]
        if instance.process is not None:
            if instance.process.poll() is None:
                return MLFlowInstance.Status.RUNNING

        return MLFlowInstance.Status.STOPPED

    def register(self, name: str, process):
        self._instances[name].process = process

    def run_fn(self, delay_in_s: int):
        txt = []
        start = None

        while not self._stop:
            if start is not None:
                if (time.time() - start) < delay_in_s:
                    time.sleep(1.0)
                    continue

            self._instances = self.reload_confd(self.config_dir)
            self.generate_nginx_instance_conf()

            running_instances = []
            if txt:
                print(f"\033[{len(txt)}A", end="")

            txt = ["\nMLFlow Instances:"]
            for name in sorted(self._instances.keys()):
                instance = self._instances[name]

                if not instance.enable:
                    if (
                        self.get_instance_status(name=name)
                        == MLFlowInstance.Status.RUNNING
                    ):
                        self.stop_instance(name)
                    txt.append(f"    {instance.name} - disabled")
                    continue

                # Dynamically start or stop instances
                if self.get_instance_status(name=name) != MLFlowInstance.Status.RUNNING:
                    self.start_instance(name)

                if instance.process.poll() is None:
                    txt.append(f"    {instance.name} - listening on: http://{instance.host_name}:{instance.port}/{instance.name}")
                    running_instances.append(instance.name)
            txt.append("Press CTRL+C to stop all running instances")
            sys.stdout.write("\n".join(txt))

            start = time.time()

    def run(self, delay_in_s: int = 10):
        t = Thread(target=self.run_fn, args=(delay_in_s,))
        t.start()
        t.join()

        # Ensure all instance are stopped when exiting
        [self.stop_instance(name) for name in self._instances]

    def terminate(self):
        self._stop = True

    def generate_nginx_instance_conf(self, template_path: Path = None):
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

        port_mapping["__default__"] = self.port_start_range

        # List existing config files to identify unneeded ones
        residual_config_files = list(output_dir.glob("*.conf"))

        # output dir for www static content such and index, and badge
        (output_dir / "www").mkdir(parents=True, exist_ok=True)

        instance_groups = {}
        for name, instance in self._instances.items():
            filename = output_dir / f"{name}.conf"
            if filename in residual_config_files:
                residual_config_files.remove(filename)

            if instance.name in port_mapping:
                instance.port = port_mapping[instance.name]
            else:
                instance.port = max(port_mapping.values()) + 1
                port_mapping[instance.name] = instance.port

            if instance.badge_prefix not in instance_groups:
                instance_groups[instance.badge_prefix] = [
                    {"name": instance.name, "enable": instance.enable}
                ]
            else:
                instance_groups[instance.badge_prefix].append(
                    {"name": instance.name, "enable": instance.enable}
                )

            badge = f"{instance.badge_prefix}-{instance.name.replace('-','_')}-{instance.badge_color}"
            with open(filename, "w") as f:
                content = mlflow_instance_template.render(
                    host_name=self.host_name,
                    name=instance.name,
                    port=instance.port,
                    badge=badge,
                    allow_cors_origin="*",
                )
                f.write(content)

            # Write out index.html file
            badge_html_filename = output_dir / "www" / f"badge-{instance.name}.html"
            with open(badge_html_filename, "w") as f:
                badge_html_template = environment.get_template("badge.html.template")
                badge_html_content = badge_html_template.render(
                    badge=badge,
                    tooltip=f"{instance.badge_prefix}-{instance.name.replace('-','_')}",
                )
                f.write(badge_html_content)

        # Cleanup old config files
        for config_file in residual_config_files:
            logger.info(
                "MLFlowOrchestrator: obsolete nginx configuration file detected."
                f"Removing: {config_file}"
            )
            config_file.unlink()

        # Write out index.html file
        index_html_template = environment.get_template("index.html.template")

        sorted_instance_groups = {}
        for k, v in instance_groups.items():
            sorted_instance_groups[k] = sorted(v, key=lambda x: x["name"])

        index_html_content = index_html_template.render(
            instance_groups=sorted_instance_groups,
            group_labels=sorted(sorted_instance_groups.keys()),
        )
        index_html_filename = output_dir / "www" / "index.html"
        with open(index_html_filename, "w") as f:
            f.write(index_html_content)

        # Write out monitor.sh file - in order to dynamically reload nginx if
        # configuration changes
        monitor_sh_template = environment.get_template("monitor.sh.template")
        monitor_sh_content = monitor_sh_template.render()
        with open(output_dir / "monitor.sh", "w") as f:
            f.write(monitor_sh_content)

        # write port_mapping
        with open(port_mapping_yaml, "w") as f:
            yaml.dump(port_mapping, f)

    def load_confd(self, directory: str | Path) -> dict[str, MLFlowInstance]:
        """
        Load all instance from a configuration file
        """
        filenames = sorted(Path(directory).glob("*.yaml"))

        instances = {}
        for file in filenames:
            try:
                instance = MLFlowInstance.from_yaml(file)
                instance.prepare(hostname=self.host_name)

                instances[instance.name] = instance

            except Exception as e:
                logger.warn(f"Loading configuration '{file}' failed -- {e}")

        return instances

    def reload_confd(self, directory: str | Path) -> dict[str, MLFlowInstance]:
        """
        Reloading instance configurations
        """
        instances = self.load_confd(directory=directory)
        updated_instances = {}
        for name, instance in instances.items():
            # Check if we find already running instances
            if name in self._instances:
                existing_instance = self._instances[name]

                # Runtime values
                instance.process = existing_instance.process
                if instance.port is None:
                    instance.port = existing_instance.port

                changes = existing_instance.collect_changes(instance)
                if changes:
                    logger.info(
                        f"MLFlowOrchestrator instance '{name}':"
                        f"configuration changed: {changes}"
                    )

            updated_instances[name] = instance
        return updated_instances
