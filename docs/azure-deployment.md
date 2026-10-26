# Azure deployment

The Azure deployment workflow is manual and only runs from `main`. It uses GitHub's OIDC token to sign in to Azure; no client secret is stored in GitHub.

## Configure Azure access

In the Azure portal:

1. Create a Microsoft Entra app registration for the GitHub deployment identity. Record its Application (client) ID and Directory (tenant) ID.
2. In the app registration, open **Certificates & secrets > Federated credentials** and add a **GitHub Actions deploying Azure resources** credential. Select the repository and the `main` branch. The subject must be `repo:<OWNER>/<REPOSITORY>:ref:refs/heads/main`, with issuer `https://token.actions.githubusercontent.com` and audience `api://AzureADTokenExchange`.
3. Create the deployment resource group in the selected Azure region.
4. In that resource group's **Access control (IAM)**, assign the app's service principal **Contributor** and **Role Based Access Control Administrator**. Contributor deploys resources; the Bicep template also creates narrowly scoped managed-identity role assignments, which requires role-assignment permission.

## Configure GitHub variables

In **Repository > Settings > Secrets and variables > Actions > Variables**, add:

| Variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | App registration Application (client) ID |
| `AZURE_TENANT_ID` | Microsoft Entra Directory (tenant) ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription ID containing the deployment resource group |
| `AZURE_ENV_NAME` | Short azd environment name, such as `prod` |
| `AZURE_LOCATION` | Allowed Azure region, such as `westus2` |
| `AZURE_RESOURCE_GROUP` | Existing resource group for this Kellan deployment |

These identifiers are not credentials. Do not add a client secret; the workflow exchanges its GitHub OIDC token for Azure access.

## Run deployment

The template targets a separate standard environment named `ml<environment><suffix>-standard-aca`, explicitly configured with `environmentMode: WorkloadProfiles` and the Consumption workload profile. Its apps are `kellan-api` and `kellan-web`. This avoids the failing private-image import path observed in the existing Express environment; it does not establish the exact underlying cause of that Express failure. Both ACR password authentication and access to the affected image manifest were independently verified from Cloud Shell.

The existing Express environment and its `api`/`web` apps are not deployment targets. The ACR, managed identity, Cosmos DB, Event Hubs, Foundry resources, and monitoring workspace retain their existing names. The replacement creates additional compute resources and a new public web URL. Keep the old resources until the replacement passes verification; removing them afterward is a separate action.

After the workflow is merged to `main`, open **Actions > Azure deployment > Run workflow** and select `main`. The workflow creates a fresh local azd environment and reads each existing app's image through Azure Resource Manager. It injects those images as literal `apiImage` and `webImage` parameters into the runner's copy of `infra/main.parameters.json`, then runs `azd provision`. Existing apps keep their deployed images during provisioning; only new apps use bootstrap images. The checked-in parameter file is not modified by this workflow run. Provisioning and running Azure resources can incur charges.

Next, `azd publish --all` builds and pushes both images. The deployment helper reads the exact `SERVICE_API_IMAGE_NAME` and `SERVICE_WEB_IMAGE_NAME` values published by that run, verifies both apps share a `WorkloadProfiles` environment, and sends each image and its registry identity together in one ARM PATCH using API version `2026-07-01`. API deploys before web. Each update has a fresh revision suffix. API bootstrap uses port 80 with no application liveness probe; installing the actual API switches ingress and its liveness probe to port 8000. Web uses port 80 throughout.

The helper validates both apps' attached identities before updating either app, waits for provisioning, and checks that each requested image and registry identity is present. Finally, it requests the public web app's `/api/config` endpoint and requires a JSON boolean `judge_mode`, checking the web-to-API proxy too. It does not run a full simulated match. A failure stops the workflow with an error; it does not automatically roll back an app already updated. Deployment runs are serialized for the configured azd environment.

For manual provisioning of an existing deployment outside this workflow, supply the current `apiImage` and `webImage` parameters. Otherwise the Bicep defaults select bootstrap images. An Azure provisioning state of `Succeeded` alone does not prove Kellan is running: also check the configured image and the public `/api/config` response.

The template enables ARM-audience authentication for the container registry, grants the apps' existing user-assigned managed identity the `AcrPull` role, and configures both Container Apps to use that identity for image pulls. The registry admin account remains enabled for the existing image-publishing flow. The web app receives the API ingress hostname from the deployment and uses it for its Nginx proxy; local Docker Compose continues to use `api:8000`.

The deployment identity's federated credential is restricted to the `main` branch. Pull requests and pushes do not provision Azure resources.

The public app offers editable fixture controls and a Judge mode preset without login. See [Judge mode](judge-mode.md) for the preset behavior, deployment limits, and verification steps.

## Verify the replacement

After a successful workflow run, get the new public URL in Cloud Shell:

```bash
az containerapp show --name kellan-web --resource-group rg-matchlens-m4-483106 \
  --query properties.configuration.ingress.fqdn --output tsv
```

Use `https://<returned-hostname>` as the application link. The workflow checks `/api/config` through this new hostname; also start a match and check the simulation, commentary, correction demo, and camera controls before updating hackathon submission links. The old `web` hostname does not redirect automatically.
