# K8s-Central ☸️

A lightweight, centralized dashboard for monitoring and managing multiple Kubernetes clusters. K8s-Central provides a unified view of your services across different environments, allowing you to track deployment statuses, image versions, and cluster health in one place.

Specifically optimized for **AWS EKS** with built-in **AWS SSO** integration.

## ✨ Features

-   **Multi-Cluster Support**: Manage multiple Kubernetes clusters by uploading their `kubeconfig` files.
-   **Service Monitoring**: Track deployments across clusters with real-time status updates (Ready replicas, Image tags).
-   **Bulk Import**: Quickly scan a namespace and map multiple deployments to your dashboard in one click.
-   **AWS SSO Integration**: Native support for EKS clusters. Log in via AWS SSO to automatically inject temporary credentials for EKS cluster access.
-   **Deep Dive**: Inspect specific deployment details (YAML-ish view) and recent events directly from the dashboard.
-   **Real-time Interaction**: Built with **FastAPI**, **Jinja2**, and **HTMX** for a smooth, single-page application feel without heavy JS frameworks.
-   **Docker Ready**: Includes a pre-configured Dockerfile with `kubectl`, `aws-cli`, and `aws-iam-authenticator` pre-installed.

## 🚀 Getting Started

### Prerequisites

-   Python 3.9+ (if running locally)
-   Docker & Docker Compose (recommended)
-   One or more Kubernetes clusters with valid `kubeconfig` files.

### Option 1: Using Docker (Recommended)

The easiest way to run K8s-Central is using Docker Compose.

1.  **Clone and Start**:
    ```bash
    git clone https://github.com/your-repo/K8s-Central.git
    cd K8s-Central
    docker-compose up -d
    ```

2.  **Access the dashboard**:
    Open [http://localhost:8000](http://localhost:8000) in your browser.

### Option 2: Local Development

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the application**:
    ```bash
    uvicorn main:app --reload
    ```

## 🔐 AWS SSO & EKS Support

K8s-Central is designed to work seamlessly with EKS clusters using AWS SSO.

1.  Click the **AWS Login** button in the navbar.
2.  Provide your **SSO Start URL** and **Region**.
3.  Follow the device authorization flow in your browser.
4.  Select your **Account** and **Role**.
5.  The application will now handle temporary credential injection automatically when querying your EKS clusters.

> **Note**: The Docker image includes a "magic shim" for `aws-vault`. If your `kubeconfig` uses `aws-vault exec`, the container will automatically bypass it and use the SSO credentials injected by the app.

## 📂 Project Structure

-   `main.py`: Core FastAPI application and API logic.
-   `templates/`: HTMX-powered HTML templates.
-   `configs/`: Directory where uploaded `kubeconfig` files are stored (Persistent volume in Docker).
-   `data.json`: Persists cluster and service mapping information (Persistent volume in Docker).
-   `Dockerfile`: Multi-tool container with `aws`, `kubectl`, and `aws-iam-authenticator`.

## 🛠 Usage

1.  **Add a Cluster**: Go to "Add Cluster", provide an alias, and upload your `kubeconfig`.
2.  **Map Services**: 
    -   Click on a Cluster.
    -   Enter a namespace and click **Scan Namespace**.
    -   Select the deployments you want to track and click **Confirm Import**.
3.  **Monitor**: The main dashboard displays a matrix of your services. Click any status badge to see live Events and Deployment details.

## 📝 License

MIT