"""Offline checks for the ARM deployment helper; no Azure requests are made."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import container_apps as deployment

IDENTITY = "/subscriptions/test/resourceGroups/test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/app"
SERVER = "test.azurecr.io"
ENVIRONMENT = "/subscriptions/test/resourceGroups/test/providers/Microsoft.App/managedEnvironments/kellan-standard"


def app(name="api"):
    return {
        "identity": {"userAssignedIdentities": {IDENTITY: {}}},
        "properties": {
            "environmentId": ENVIRONMENT,
            "configuration": {"registries": None},
            "template": {
                "containers": [
                    {
                        "name": name,
                        "image": f"{SERVER}/{name}:previous",
                        "env": [{"name": "KEEP", "value": "yes"}],
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ]
            },
        },
    }


class DeploymentTests(unittest.TestCase):
    def test_image_and_identity_are_sent_in_one_request(self):
        current = app()
        original = copy.deepcopy(current)
        body = deployment.deployment_body(
            current, "api", f"{SERVER}/api:new", SERVER, IDENTITY
        )
        properties = body["properties"]
        self.assertEqual(
            properties["configuration"]["registries"],
            [{"server": SERVER, "identity": IDENTITY}],
        )
        container = properties["template"]["containers"][0]
        self.assertEqual(container["image"], f"{SERVER}/api:new")
        self.assertEqual(
            container["env"], original["properties"]["template"]["containers"][0]["env"]
        )
        self.assertEqual(container["resources"], {"cpu": 0.5, "memory": "1Gi"})
        self.assertEqual(current, original)
        self.assertTrue(properties["template"]["revisionSuffix"].startswith("deploy-"))
        self.assertEqual(properties["configuration"]["ingress"]["targetPort"], 8000)
        self.assertEqual(container["probes"][0]["httpGet"]["port"], 8000)

    def test_targets_separate_app_names(self):
        with patch.dict(
            deployment.os.environ,
            {"AZURE_SUBSCRIPTION_ID": "test", "AZURE_RESOURCE_GROUP": "test"},
        ):
            self.assertIn("/containerApps/kellan-api?", deployment.app_url("api"))
            self.assertIn("/containerApps/kellan-web?", deployment.app_url("web"))

    def test_web_port_and_new_revision_suffix(self):
        first = deployment.deployment_body(
            app("web"), "web", f"{SERVER}/web:new", SERVER, IDENTITY
        )
        second = deployment.deployment_body(
            app("web"), "web", f"{SERVER}/web:new", SERVER, IDENTITY
        )
        self.assertEqual(
            first["properties"]["configuration"]["ingress"]["targetPort"], 80
        )
        self.assertNotEqual(
            first["properties"]["template"]["revisionSuffix"],
            second["properties"]["template"]["revisionSuffix"],
        )

    def test_replaces_target_registry_and_retains_other_registries(self):
        current = app()
        current["properties"]["configuration"]["registries"] = [
            {"server": SERVER, "username": "old", "passwordSecretRef": "old-secret"},
            {"server": "other.example", "identity": IDENTITY},
        ]
        body = deployment.deployment_body(
            current, "api", f"{SERVER}/api:new", SERVER, IDENTITY
        )
        registries = body["properties"]["configuration"]["registries"]
        self.assertEqual(len(registries), 2)
        self.assertEqual(registries[0]["server"], "other.example")
        self.assertNotIn("passwordSecretRef", registries[1])

    def test_rejects_missing_identity_and_wrong_registry(self):
        current = app()
        with self.assertRaisesRegex(RuntimeError, "outside the expected registry"):
            deployment.deployment_body(
                current, "api", "other.azurecr.io/api:new", SERVER, IDENTITY
            )
        current["identity"]["userAssignedIdentities"] = {}
        with self.assertRaisesRegex(RuntimeError, "not attached"):
            deployment.deployment_body(
                current, "api", f"{SERVER}/api:new", SERVER, IDENTITY
            )

    def test_provisioning_keeps_both_existing_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parameters.json"
            path.write_text(
                json.dumps({"parameters": {"environmentName": {"value": "prod"}}})
            )
            with (
                patch.object(
                    deployment,
                    "arm_request",
                    side_effect=[(app(), {}), (app("web"), {})],
                ),
                patch.object(deployment, "app_url", side_effect=lambda name: name),
            ):
                deployment.prepare("token", path)
            parameters = json.loads(path.read_text())["parameters"]
            self.assertEqual(parameters["apiImage"]["value"], f"{SERVER}/api:previous")
            self.assertEqual(parameters["webImage"]["value"], f"{SERVER}/web:previous")
            self.assertEqual(parameters["environmentName"]["value"], "prod")

    def test_only_not_found_uses_bootstrap_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parameters.json"
            original = '{"parameters": {}}'
            path.write_text(original)
            with (
                patch.object(deployment, "app_url", return_value="url"),
                patch.object(
                    deployment,
                    "arm_request",
                    side_effect=HTTPError("url", 404, "missing", {}, None),
                ),
            ):
                deployment.prepare("token", path)
            self.assertNotIn("apiImage", json.loads(path.read_text())["parameters"])
            path.write_text(original)
            forbidden = HTTPError("url", 403, "forbidden", {}, None)
            self.addCleanup(forbidden.close)
            with (
                patch.object(deployment, "app_url", return_value="url"),
                patch.object(deployment, "arm_request", side_effect=forbidden),
                self.assertRaises(HTTPError),
            ):
                deployment.prepare("token", path)
            self.assertEqual(path.read_text(), original)

    def test_validates_web_before_mutating_api(self):
        invalid_web = app("web")
        invalid_web["identity"]["userAssignedIdentities"] = {}
        values = {
            "AZURE_CONTAINER_REGISTRY_ENDPOINT": SERVER,
            "AZURE_CONTAINER_APPS_IDENTITY_ID": IDENTITY,
            "SERVICE_API_IMAGE_NAME": f"{SERVER}/api:new",
            "SERVICE_WEB_IMAGE_NAME": f"{SERVER}/web:new",
        }
        with (
            patch.dict(deployment.os.environ, {"AZURE_ENV_NAME": "prod"}),
            patch.object(deployment, "azd", side_effect=lambda *args: values[args[2]]),
            patch.object(deployment, "app_url", side_effect=lambda name: name),
            patch.object(
                deployment, "arm_request", side_effect=[(app(), {}), (invalid_web, {})]
            ) as request,
        ):
            with self.assertRaisesRegex(RuntimeError, "not attached"):
                deployment.deploy("token")
            self.assertEqual(request.call_count, 2)
            self.assertTrue(all(len(call.args) == 2 for call in request.call_args_list))

    def test_failed_azure_operation_is_reported(self):
        with (
            patch.object(
                deployment,
                "arm_request",
                return_value=(
                    {"status": "Failed", "error": {"code": "ImagePullFailed"}},
                    {},
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "ImagePullFailed"),
        ):
            deployment.wait_for_operation("url", "token")

    def test_rejects_express_environment_before_updates(self):
        values = {
            "AZURE_CONTAINER_REGISTRY_ENDPOINT": SERVER,
            "AZURE_CONTAINER_APPS_IDENTITY_ID": IDENTITY,
            "SERVICE_API_IMAGE_NAME": f"{SERVER}/api:new",
            "SERVICE_WEB_IMAGE_NAME": f"{SERVER}/web:new",
        }
        responses = [
            (app(), {}),
            (app("web"), {}),
            ({"properties": {"environmentMode": "Express"}}, {}),
        ]
        with (
            patch.dict(deployment.os.environ, {"AZURE_ENV_NAME": "prod"}),
            patch.object(deployment, "azd", side_effect=lambda *args: values[args[2]]),
            patch.object(deployment, "app_url", side_effect=lambda name: name),
            patch.object(deployment, "arm_request", side_effect=responses) as request,
            self.assertRaisesRegex(RuntimeError, "Expected WorkloadProfiles"),
        ):
            deployment.deploy("token")
        self.assertEqual(request.call_count, 3)
        self.assertTrue(all(len(call.args) == 2 for call in request.call_args_list))

    def test_deploys_published_tags_then_checks_web_to_api(self):
        api = app()
        web = app("web")
        for name, current in (("api", api), ("web", web)):
            current["properties"]["provisioningState"] = "Succeeded"
            current["properties"]["template"]["containers"][0]["image"] = (
                f"{SERVER}/{name}:new"
            )
            current["properties"]["configuration"]["registries"] = [
                {"server": SERVER, "identity": IDENTITY}
            ]
        web["properties"]["configuration"]["ingress"] = {"fqdn": "web.example"}
        values = {
            "AZURE_CONTAINER_REGISTRY_ENDPOINT": SERVER,
            "AZURE_CONTAINER_APPS_IDENTITY_ID": IDENTITY,
            "SERVICE_API_IMAGE_NAME": f"{SERVER}/api:new",
            "SERVICE_WEB_IMAGE_NAME": f"{SERVER}/web:new",
        }
        responses = [
            (app(), {}),
            (app("web"), {}),
            ({"properties": {"environmentMode": "WorkloadProfiles"}}, {}),
            ({}, {}),
            (api, {}),
            ({}, {}),
            (web, {}),
            (web, {}),
        ]
        with (
            patch.dict(deployment.os.environ, {"AZURE_ENV_NAME": "prod"}),
            patch.object(deployment, "azd", side_effect=lambda *args: values[args[2]]),
            patch.object(deployment, "app_url", side_effect=lambda name: name),
            patch.object(deployment, "arm_request", side_effect=responses) as request,
            patch.object(
                deployment, "urlopen", return_value=io.BytesIO(b'{"judge_mode": false}')
            ) as public_request,
        ):
            deployment.deploy("token")
        updates = [call for call in request.call_args_list if len(call.args) > 2]
        self.assertEqual([call.args[0] for call in updates], ["api", "web"])
        self.assertTrue(all(call.args[2] == "PATCH" for call in updates))
        self.assertEqual(
            updates[0].args[3]["properties"]["template"]["containers"][0]["image"],
            f"{SERVER}/api:new",
        )
        public_request.assert_called_once_with(
            "https://web.example/api/config", timeout=15
        )

    def test_operation_is_polled_until_succeeded(self):
        with (
            patch.object(
                deployment,
                "arm_request",
                side_effect=[
                    ({"status": "InProgress"}, {}),
                    ({"status": "Succeeded"}, {}),
                ],
            ) as request,
            patch.object(deployment.time, "sleep"),
        ):
            deployment.wait_for_operation("url", "token")
            self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
