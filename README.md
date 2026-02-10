# K8s-Central ☸️

A lightweight, centralized dashboard for monitoring and managing multiple Kubernetes clusters. K8s-Central provides a unified view of your services across different environments, allowing you to track deployment statuses, image versions, and cluster health in one place.

Specifically optimized for **AWS EKS** with built-in **AWS SSO** integration.

## ✨ Features

- **Multi-Cluster Support**: Manage multiple Kubernetes clusters by uploading their `kubeconfig` files.
- **Service Monitoring**: Track deployments across clusters with real-time status updates (Ready replicas, Image tags).
- **Bulk Import**: Quickly scan a namespace and map multiple deployments to your dashboard in one click.
- **AWS SSO Integration**: Native support for EKS clusters. Log in via AWS SSO to automatically inject temporary credentials for EKS cluster access.
- **Zero-Setup Persistence**: Smart folder-based architecture ensures Docker volumes work instantly on Windows, Mac, and Linux without manual file creation.
- **Docker Ready**: Includes a pre-configured Dockerfile with `kubectl`, `aws-cli`, and `aws-iam-authenticator` pre-installed.

## 🚀 Getting Started

### Option 1: Quickstart (Docker) - Recommended

No cloning or setup scripts required. Just run the command for your OS. This will automatically create the necessary data folders on your machine.

**Windows (PowerShell):**

```powershell
docker run -d -p 8000:8000 --name k8s-central `
  -v "${PWD}/k8s-data:/app/data" `
  -v "${PWD}/k8s-configs:/app/configs" `
  -e AWS_DEFAULT_REGION=us-east-1 `
  akhil850/k8s-central:latest
```

Mac / Linux:

```Bash
docker run -d -p 8000:8000 --name k8s-central \
  -v "$(pwd)/k8s-data:/app/data" \
  -v "$(pwd)/k8s-configs:/app/configs" \
  -e AWS_DEFAULT_REGION=us-east-1 \
  akhil850/k8s-central:latest
```

### Option 2: Using Docker Compose

If you cloned the repo, you can use Compose.

```Bash
docker-compose up -d --build
Access: http://localhost:8000
```

### Option 3: Local Development (Python)

Install dependencies:

Bash
pip install -r requirements.txt
Run the application:

```Bash
uvicorn main:app --reload
```

## 🔐 AWS SSO & EKS Support

K8s-Central is designed to work seamlessly with EKS clusters using AWS SSO.

- Click the AWS Login button in the navbar.

- Provide your SSO Start URL and Region.

- Follow the device authorization flow in your browser.

- Select your Account and Role.

The application will now handle temporary credential injection automatically when querying your EKS clusters.

> Note: The Docker image includes a shim for aws-vault. If your kubeconfig uses aws-vault exec, the container will automatically bypass it and use the SSO credentials injected by the app.

## 📂 Project Structure

- main.py: Core FastAPI application and API logic.

- templates/: HTMX-powered HTML templates.

- configs/: Directory where uploaded kubeconfig files are stored.

- data/: Directory containing data.json (The persistent database).

- Dockerfile: Multi-tool container with aws, kubectl, and aws-iam-authenticator.

## 🛠 Usage

- Add a Cluster: Go to "Add Cluster", provide an alias, and upload your kubeconfig.

- Map Services:

- Click on a Cluster name to view details.

- Click Import Namespace.

- Enter a namespace (e.g., default) and click Scan.

- Select the deployments you want to track and click Confirm Import.

Monitor: The main dashboard displays a matrix of your services. Click any status badge to see live Events and Deployment details.
