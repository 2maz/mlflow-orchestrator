from mlflow_orchestrator.cli.base import BaseParser

from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path
import signal
import os
import socket

from mlflow_orchestrator.base import MLFlowOrchestrator

logger = getLogger(__name__)

ML_BASE_DIR = f"{os.environ['HOME']}/mlflow-orchestrator-workspace"
ML_CONFIG_DIR = "conf.d"


class RunParser(BaseParser):
    def __init__(self, parser: ArgumentParser):
        super().__init__(parser=parser)

        parser.add_argument(
            "--base-dir",
            default=ML_BASE_DIR,
            type=str,
            help=f"top level folder where project subfolder are created"
            f"(default: {ML_BASE_DIR})",
        )
        parser.add_argument(
            "-c",
            "--config-dir",
            default=None,
            type=str,
            help=f"Configuration directory (default: {ML_CONFIG_DIR} in base-dir)",
        )
        parser.add_argument(
            "--host-name", default=None, help="Host IP for the hosted instances"
        )
        parser.add_argument(
            "--port-start-range",
            default=10000,
            type=int,
            help="Start of the port range used for hosted instances (default: 10000)",
        )

    def get_ip(self):
        """
        Identify current systems IP address by connection to a typically available dns server
        """
        for t in [("8.8.8.8", 1253)]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(t)
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception as e:
                logger.warning(e)

    def execute(self, args):
        super().execute(args)

        base_dir = Path(args.base_dir)
        if args.config_dir is None:
            config_dir = base_dir / ML_CONFIG_DIR
        else:
            config_dir = Path(args.config_dir)

        host_name = args.host_name
        if args.host_name is None:
            host_name = self.get_ip()

        orchestrator = MLFlowOrchestrator(
            config_dir=config_dir,
            base_dir=base_dir,
            host_name=host_name,
            port_start_range=args.port_start_range,
        )

        def signal_handler(sig, frame):
            orchestrator.terminate()

        signal.signal(signal.SIGINT, signal_handler)

        try:
            orchestrator.run()
        except Exception as e:
            logger.error(e)
        finally:
            orchestrator.terminate()
