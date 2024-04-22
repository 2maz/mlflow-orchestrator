from mlflow_orchestrator.cli.base import BaseParser
from argparse import ArgumentParser
import importlib

if not hasattr(importlib, "resources"):
    import importlib_resources

    setattr(importlib, "resources", importlib_resources)
from jinja2 import Environment, FileSystemLoader
from pathlib import Path


class SetupParser(BaseParser):
    def __init__(self, parser: ArgumentParser):
        super().__init__(parser=parser)

        parser.add_argument(
            "--nginx",
            action="store_true",
            default=False,
            help="Consider nginx running on this system",
        )

        parser.add_argument(
            "--minio",
            action="store_true",
            default=False,
            help="Consider nginx running on this system",
        )
        parser.add_argument(
            "--minio-hostname",
            default=None,
            help="Use minio running on the system given by hostname",
        )

        parser.add_argument("-o", "--output-dir", default=None, help="Output directory")

    def execute(self, args):
        super().execute(args)

        template_path = importlib.resources.files("mlflow_orchestrator").joinpath(
            "templates"
        )
        environment = Environment(loader=FileSystemLoader(searchpath=template_path))

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        docker_compose_yaml = environment.get_template("docker-compose.yaml.template")
        if args.nginx:
            nginx_default_template = environment.get_template(
                "nginx/nginx-default.conf.template"
            )
            content = nginx_default_template.render(
                nginx_port="8888",
                minio_hostname=args.minio_hostname,
                use_nginx=args.nginx,
            )

            path = output_dir / "nginx-default.conf.template"
            with open(path, "w") as f:
                f.write(content)

        content = docker_compose_yaml.render(use_nginx=args.nginx, use_minio=args.minio)
        path = output_dir / "docker-compose.yaml"
        with open(path, "w") as f:
            f.write(content)
