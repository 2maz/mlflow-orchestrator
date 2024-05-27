# MLFlow Orchestrator

MLFlow Orchestrator permits a unified configuration for multiple mlflow instances in combination with nginx.
An additional minio-based artifact storage can optionally be added.

## Installation

Install the python package as usual.

## Usage

In order to see available option of the command line interface use:
```
mlflow-orchestrator --help
```

Subcommands can likewise be explored:

```
mlflow-orchestrator setup --help
```

If order to create the multi-instance setup use the following commands, to create
an nginx configuration in combination with a minio setup for a single mlflow instance.
The configuration will be stored in /tmp/mflow-orchestrator

```
mlflow-orchestrator setup --nginx --minio -o /tmp/mlflow-orchestrator/
```


You can then run the orchestrator with (replace X.X.X.X with the actual host ip to use):

```
cd /tmp/mlflow-orchestrator/
docker-compose up -d
mlflow-orchestrator run --host X.X.X.X --base-dir /tmp/mlflow-orchestrator
```

## Configuration

### Basic

A simple configuration file for a mlflow instance might look as follows:

```
name: my-instance
enable: True          # Whether to start or not
badge-prefix: project # With nginx the top-left image in your mlflow instance will be replaced with an ioshield using <badge-prefix>-<name>
```

### Configuration with authentication

The configuration option found here are mainly used to render an mlflow-specific configuration under <base_dir>/instances/<name>/, e.g.,
/tmp/mlflow-orchestrator/instance/my-project.

Just check the folder after running setup.
The [authentication](https://mlflow.org/docs/latest/auth/index.html?highlight=default_permission#configuration) can be defined under top level: 'auth' key.

```
name: my-project
enable: True
badge_prefix: project
auth:
  auth_type: basic-auth
  admin_username: admin
  admin_password: my-project-admin-passwd
artifacts:
  serve: True
  destination: s3://my-project/
environment:
  # Example with access to a local MINIO Server
  # https://mlflow.org/docs/latest/tracking/artifacts-stores.html?highlight=aws_
  AWS_ACCESS_KEY_ID: your_access_key_id            # generate access-token via minio web-interface
  AWS_SECRET_ACCESS_KEY: your_secret_access_key    # generate access-token via minio web-interface
  MLFLOW_S3_ENDPOINT_URL: http://hostname:9000     # where the minio instance runs
  MLFLOW_S3_IGNORE_TLS: True
```



## Copyright

(c) Copyright 2024 Thomas M. Roehr, Simula Research Laboratory
