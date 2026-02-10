# K8s-Central

A lightweight, centralized dashboard for monitoring and managing multiple Kubernetes clusters. K8s-Central provides a unified view of your services across different environments, allowing you to track deployment statuses, image versions, and cluster health in one place.

## Features

- **Multi-Cluster Support**: Manage multiple Kubernetes clusters by uploading their `kubeconfig` files.
- **Service Monitoring**: Track deployments across clusters with real-time status updates (Ready replicas, Image tags).
- **Bulk Import**: Quickly map multiple deployments from a specific namespace to your dashboard.
- **Cluster Insights**: View cluster health, Kubernetes version, and node counts at a glance.
- **Deep Dive**: Inspect specific deployment details and recent events directly from the dashboard.
- **Responsive UI**: Built with FastAPI, Jinja2, and HTMX for a smooth, interactive experience.

## Tech Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Frontend**: [HTMX](https://htmx.org/), [Jinja2 Templates](https://jinja.palletsprojects.com/)
- **Kubernetes Integration**: [Official Python Client](https://github.com/kubernetes-client/python)
- **Data Store**: Local `data.json` (File-based DB)

## Getting Started

### Prerequisites

- Python 3.8+
- One or more Kubernetes clusters with valid `kubeconfig` files.

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-repo/K8s-Central.git
    cd K8s-Central
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the application**:
    ```bash
    uvicorn main:app --reload
    ```

4.  **Access the dashboard**:
    Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Project Structure

- `main.py`: Core FastAPI application and API logic.
- `templates/`: HTML templates using Jinja2 and HTMX.
- `configs/`: Directory where uploaded `kubeconfig` files are stored.
- `data.json`: Persists cluster and service mapping information.
- `requirements.txt`: Python dependencies.

## Usage

1.  **Add a Cluster**: Go to "Add Cluster", provide an alias, and upload your `kubeconfig` file.
2.  **Map Services**: Within a cluster view, you can manually add service mappings or use the **Scan Namespace** feature to bulk-import deployments.
3.  **Monitor**: The main dashboard displays a matrix of your services across all registered clusters.

## License

MIT
