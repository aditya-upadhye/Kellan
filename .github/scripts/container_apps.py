"""Preserve and deploy images in Kellan's standard Container Apps environment."""

import argparse
import copy
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ARM = "https://management.azure.com"
API_VERSION = "2026-07-01"
APPS = {"api": "kellan-api", "web": "kellan-web"}


def azd(*arguments):
    return subprocess.check_output(["azd", *arguments], text=True).strip()


def arm_request(url, token, method="GET", body=None):
    if not url.startswith(ARM + "/"):
        raise RuntimeError("Unexpected Azure Resource Manager URL")
    request = Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urlopen(request, timeout=60) as response:
        content = response.read()
        return (json.loads(content) if content else {}), response.headers


def app_url(name):
    subscription = os.environ["AZURE_SUBSCRIPTION_ID"]
    group = os.environ["AZURE_RESOURCE_GROUP"]
    return (
        f"{ARM}/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.App/containerApps/{APPS[name]}?api-version={API_VERSION}"
    )


def prepare(token, parameters_path):
    """Pass existing images as literal Bicep parameters in the runner's checkout."""
    parameters = json.loads(parameters_path.read_text())
    for name in APPS:
        try:
            current, _ = arm_request(app_url(name), token)
        except HTTPError as error:
            if error.code == 404:
                error.close()
                print(f"{name}: new app; using the Bicep bootstrap image")
                continue
            raise
        container = next(
            (
                item
                for item in current["properties"]["template"]["containers"]
                if item["name"] == name
            ),
            None,
        )
        if not container or not container.get("image"):
            raise RuntimeError(
                f"{name}: cannot determine current image; provisioning stopped"
            )
        parameters["parameters"][f"{name}Image"] = {"value": container["image"]}
        print(f"{name}: retaining {container['image']} during provisioning")
    parameters_path.write_text(json.dumps(parameters, indent=2) + "\n")


def deployment_body(current, name, image, server, identity):
    if identity.lower() not in {
        key.lower()
        for key in (current.get("identity") or {}).get("userAssignedIdentities") or {}
    }:
        raise RuntimeError(f"{name}: expected image-pull identity is not attached")
    if not image.startswith(server + "/"):
        raise RuntimeError(f"{name}: published image is outside the expected registry")
    containers = copy.deepcopy(current["properties"]["template"]["containers"])
    matches = [container for container in containers if container["name"] == name]
    if len(matches) != 1:
        raise RuntimeError(f"{name}: expected exactly one matching container")
    matches[0]["image"] = image
    if name == "api":
        matches[0]["probes"] = [
            {
                "type": "Liveness",
                "httpGet": {"path": "/healthz", "port": 8000, "scheme": "HTTP"},
                "initialDelaySeconds": 10,
                "periodSeconds": 30,
            }
        ]
    registries = [
        registry
        for registry in current["properties"]["configuration"].get("registries") or []
        if registry["server"].lower() != server.lower()
    ]
    registries.append({"server": server, "identity": identity})
    return {
        "properties": {
            "configuration": {
                "registries": registries,
                "ingress": {"targetPort": 8000 if name == "api" else 80},
            },
            "template": {
                "containers": containers,
                "revisionSuffix": f"deploy-{uuid.uuid4().hex[:12]}",
            },
        }
    }


def wait_for_operation(url, token, timeout=1200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        operation, _ = arm_request(url, token)
        status = operation.get("status", "")
        if status.lower() == "succeeded":
            return
        if status.lower() in {"failed", "canceled", "cancelled"}:
            raise RuntimeError(
                f"Azure deployment operation failed: {json.dumps(operation)}"
            )
        time.sleep(10)
    raise RuntimeError("Timed out waiting for Azure deployment operation")


def deploy(token):
    environment = os.environ["AZURE_ENV_NAME"]
    server = azd(
        "env",
        "get-value",
        "AZURE_CONTAINER_REGISTRY_ENDPOINT",
        "--environment",
        environment,
    )
    identity = azd(
        "env",
        "get-value",
        "AZURE_CONTAINER_APPS_IDENTITY_ID",
        "--environment",
        environment,
    )
    # Validate both requests before updating either app. Use this run's published tags.
    requests = []
    environment_ids = set()
    for name in APPS:
        image = azd(
            "env",
            "get-value",
            f"SERVICE_{name.upper()}_IMAGE_NAME",
            "--environment",
            environment,
        )
        current, _ = arm_request(app_url(name), token)
        properties = current["properties"]
        environment_id = properties.get("environmentId") or properties.get(
            "managedEnvironmentId"
        )
        if not environment_id:
            raise RuntimeError(f"{name}: environment ID is missing")
        environment_ids.add(environment_id)
        body = deployment_body(current, name, image, server, identity)
        requests.append((name, image, body))

    if len(environment_ids) != 1:
        raise RuntimeError("API and web must use the same standard environment")
    environment_id = next(iter(environment_ids))
    managed_environment, _ = arm_request(
        f"{ARM}{environment_id}?api-version={API_VERSION}", token
    )
    mode = managed_environment["properties"].get("environmentMode")
    if mode != "WorkloadProfiles":
        raise RuntimeError(
            f"Expected WorkloadProfiles environment, found {mode}; deployment stopped"
        )
    print(f"Standard environment verified: {environment_id}", flush=True)

    for name, image, body in requests:
        print(f"{name}: deploying {image} with its registry identity", flush=True)
        _, headers = arm_request(app_url(name), token, "PATCH", body)
        operation_url = headers.get("Azure-AsyncOperation")
        if operation_url:
            wait_for_operation(operation_url, token)
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            current, _ = arm_request(app_url(name), token)
            state = current["properties"].get("provisioningState", "")
            if state.lower() in {"failed", "canceled", "cancelled"}:
                raise RuntimeError(f"{name}: provisioning {state}")
            properties = current["properties"]
            image_matches = any(
                item["name"] == name and item["image"] == image
                for item in properties["template"]["containers"]
            )
            registry_matches = any(
                item["server"].lower() == server.lower()
                and (item.get("identity") or "").lower() == identity.lower()
                for item in properties["configuration"].get("registries") or []
            )
            if state.lower() == "succeeded" and image_matches and registry_matches:
                print(
                    f"{name}: provisioning succeeded; image and registry identity verified"
                )
                break
            time.sleep(10)
        else:
            raise RuntimeError(f"{name}: timed out verifying image deployment")

    web, _ = arm_request(app_url("web"), token)
    host = web["properties"]["configuration"]["ingress"]["fqdn"]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with urlopen(f"https://{host}/api/config", timeout=15) as response:
                config = json.load(response)
            if isinstance(config, dict) and isinstance(config.get("judge_mode"), bool):
                print(f"Public web-to-API check passed: https://{host}/api/config")
                return
        except (URLError, ValueError, TimeoutError):
            pass
        time.sleep(10)
    raise RuntimeError("Public web-to-API config check failed after deployment")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "deploy"))
    args = parser.parse_args()
    token = json.loads(
        azd("auth", "token", "--scope", ARM + "/.default", "--output", "json")
    )["token"]
    try:
        if args.command == "prepare":
            prepare(token, Path("infra/main.parameters.json"))
        else:
            deploy(token)
    except HTTPError as error:
        with error:
            detail = error.read().decode()
        raise SystemExit(f"Azure request failed ({error.code}): {detail}") from None
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
