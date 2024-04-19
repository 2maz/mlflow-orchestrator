import pytest
import yaml


from mlflow_orchestrator.config import MLFlowInstance, MLFlowAuth


@pytest.fixture
def mlflow_instance_config():
    return {
        "name": "instance_config_name",
        "auth": {
            "auth_type": "basic-auth",
            "admin_username": "admin",
            "admin_password": "password",
        },
    }


@pytest.fixture
def mlflow_instance_configfile(mlflow_instance_config, tmp_path):
    test_yaml = tmp_path / "test_yaml"
    with open(test_yaml, "w") as f:
        yaml.dump(mlflow_instance_config, f)

    return test_yaml


def test_MLFlowInstance(mlflow_instance_config, mlflow_instance_configfile):
    mlflow_instance = MLFlowInstance.from_yaml(filename=mlflow_instance_configfile)

    assert mlflow_instance.name == mlflow_instance_config["name"]
    assert mlflow_instance.auth == MLFlowAuth(**mlflow_instance_config["auth"])

    breakpoint()
