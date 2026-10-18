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
| `AZURE_RESOURCE_GROUP` | Existing resource group for this MatchLens deployment |

These identifiers are not credentials. Do not add a client secret; the workflow exchanges its GitHub OIDC token for Azure access.

## Run deployment

After the workflow is merged to `main`, open **Actions > Azure deployment > Run workflow** and select `main`. The workflow creates a fresh local azd environment, then runs `azd up` to provision or update the Bicep resources and deploy both services. It serializes deployment runs for the configured azd environment. Provisioning and running Azure resources can incur charges.

The template enables the container registry admin account and stores its password as a secret in each Container App for image pulls. The web app receives the API ingress hostname from the deployment and uses it for its Nginx proxy; local Docker Compose continues to use `api:8000`.

The deployment identity's federated credential is restricted to the `main` branch. Pull requests and pushes do not provision Azure resources.

The public app starts in Judge mode without login. See [Judge mode](judge-mode.md) for the preset behavior, deployment limits, and verification steps.
