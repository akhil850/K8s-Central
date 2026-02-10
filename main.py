import os
import json
import shutil
import time
import re
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, UploadFile, File, Form, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from kubernetes import client, config

app = FastAPI()
templates = Jinja2Templates(directory="templates")

os.makedirs("configs", exist_ok=True)

# --- GLOBAL CACHE ---
CACHE = {
    "stats": {},      
    "statuses": {},   
    "timestamp": 0    
}

def get_last_updated():
    if CACHE["timestamp"] == 0: return "Never"
    dt = datetime.fromtimestamp(CACHE["timestamp"])
    return dt.strftime("%H:%M:%S")

# --- DB HELPERS ---
def load_db():
    try:
        if not os.path.exists("data.json"):
            return {"clusters": [], "services": []}
        with open("data.json", "r") as f:
            content = f.read()
            if not content: return {"clusters": [], "services": []}
            return json.loads(content)
    except Exception:
        return {"clusters": [], "services": []}

def save_db(data):
    with open("data.json", "w") as f:
        json.dump(data, f, indent=4)

def guess_ui_name(deployment_name: str, existing_names: List[str]) -> str:
    if deployment_name in existing_names: return deployment_name
    matches = [name for name in existing_names if deployment_name.startswith(name)]
    if matches: return max(matches, key=len)
    clean = re.sub(r'-(blue|green|canary|prod|dev|staging|v\d+)$', '', deployment_name)
    return clean

# --- PAGE ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data = load_db()
    service_map = {}
    for svc in data["services"]:
        s_name = svc["ui_name"]
        if s_name not in service_map:
            service_map[s_name] = {}
        for cluster_id, details in svc["clusters"].items():
            service_map[s_name][cluster_id] = details["namespace"]

    final_services = []
    for name, cluster_dict in service_map.items():
        final_services.append({"ui_name": name, "cluster_map": cluster_dict})

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "clusters": data["clusters"], 
        "services": final_services, 
        "last_updated": get_last_updated(),
        "ts": int(time.time())
    })

@app.get("/cluster/{cluster_id}", response_class=HTMLResponse)
async def cluster_detail(request: Request, cluster_id: str):
    data = load_db()
    cluster = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster: return HTMLResponse("Cluster not found", status_code=404)
    
    cluster_services = []
    for s in data["services"]:
        if cluster_id in s["clusters"]:
            flat_svc = {
                "ui_name": s["ui_name"],
                "deployment": s["clusters"][cluster_id]["deployment"],
                "namespace": s["clusters"][cluster_id]["namespace"]
            }
            cluster_services.append(flat_svc)

    return templates.TemplateResponse("cluster_detail.html", {
        "request": request, 
        "cluster": cluster, 
        "services": cluster_services, 
        "last_updated": get_last_updated(),
        "ts": int(time.time())
    })

@app.get("/add-cluster", response_class=HTMLResponse)
async def add_cluster_view(request: Request):
    return templates.TemplateResponse("add_cluster.html", {"request": request})

# --- ACTION ROUTES ---

@app.post("/refresh-all")
async def refresh_all(request: Request):
    CACHE["stats"] = {}
    CACHE["statuses"] = {}
    CACHE["timestamp"] = time.time()
    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=303)

@app.post("/add-cluster")
async def add_cluster_logic(alias: str = Form(...), file: UploadFile = File(...)):
    file_location = f"configs/{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    data = load_db()
    if any(c['alias'] == alias for c in data['clusters']):
         return HTMLResponse("Error: Cluster alias already exists! <a href='/add-cluster'>Go back</a>")
    data["clusters"].append({"id": alias.lower().replace(" ", "-"), "alias": alias, "config_path": file_location})
    save_db(data)
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete-cluster")
async def delete_cluster(cluster_id: str = Form(...)):
    data = load_db()
    data["clusters"] = [c for c in data["clusters"] if c["id"] != cluster_id]
    for svc in data["services"]:
        if cluster_id in svc["clusters"]: del svc["clusters"][cluster_id]
    data["services"] = [s for s in data["services"] if len(s["clusters"]) > 0]
    save_db(data)
    CACHE["stats"].pop(cluster_id, None)
    return RedirectResponse(url="/", status_code=303)

@app.post("/add-service")
async def add_service(cluster_id: str = Form(...), ui_name: str = Form(...), deployment_name: str = Form(...), namespace: str = Form(...)):
    data = load_db()
    existing = next((s for s in data['services'] if s['ui_name'] == ui_name), None)
    entry = {"deployment": deployment_name, "namespace": namespace}
    if existing:
        existing["clusters"][cluster_id] = entry
    else:
        data["services"].append({"ui_name": ui_name, "clusters": {cluster_id: entry}})
    save_db(data)
    CACHE["statuses"].pop(f"{cluster_id}_{ui_name}", None)
    return RedirectResponse(url=f"/cluster/{cluster_id}", status_code=303)

@app.post("/unmap-service")
async def unmap_service(cluster_id: str = Form(...), ui_name: str = Form(...)):
    data = load_db()
    svc = next((s for s in data["services"] if s['ui_name'] == ui_name), None)
    if svc and cluster_id in svc["clusters"]:
        del svc["clusters"][cluster_id]
        if not svc["clusters"]:
            data["services"] = [s for s in data["services"] if s['ui_name'] != ui_name]
        save_db(data)
    CACHE["statuses"].pop(f"{cluster_id}_{ui_name}", None)
    return RedirectResponse(url=f"/cluster/{cluster_id}", status_code=303)

# --- API ENDPOINTS ---

@app.get("/api/cluster-stats/{cluster_id}")
def get_cluster_stats(cluster_id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if cluster_id in CACHE["stats"]: return HTMLResponse(CACHE["stats"][cluster_id])

    data = load_db()
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster_info: return HTMLResponse("""<div class="alert alert-danger py-1 px-2 mt-2 mb-0 small">Config Missing</div>""")

    try:
        api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
        version = client.VersionApi(api_client=api_client).get_code().git_version
        nodes = len(client.CoreV1Api(api_client=api_client).list_node().items)
        html_out = f"""
            <div class="d-flex justify-content-between mt-3">
                <span class="badge bg-success bg-opacity-10 text-success border border-success">Online</span>
                <span class="small fw-bold text-dark">{version}</span>
            </div>
            <div class="mt-2 small text-muted">Nodes: <strong>{nodes}</strong></div>
        """
        CACHE["stats"][cluster_id] = html_out
        return HTMLResponse(html_out)
    except Exception:
        return HTMLResponse("""<div class="alert alert-danger py-1 px-2 mt-2 mb-0 small">Offline</div>""")

@app.get("/api/status/{cluster_id}/{ui_name}")
def get_k8s_status(cluster_id: str, ui_name: str, response: Response, ts: int = 0):
    response.headers["Cache-Control"] = "no-store"
    cache_key = f"{cluster_id}_{ui_name}"
    if cache_key in CACHE["statuses"]: return HTMLResponse(CACHE["statuses"][cache_key])
        
    data = load_db()
    svc = next((s for s in data["services"] if s['ui_name'] == ui_name), None)
    cell_start, cell_end = '<td class="status-cell align-middle">', '</td>'
    
    if not svc or cluster_id not in svc["clusters"]:
        return HTMLResponse(f'{cell_start}<span class="text-muted opacity-25">-</span>{cell_end}')

    details = svc["clusters"][cluster_id]
    deployment_name, namespace = details["deployment"], details["namespace"]
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    ns_badge = f'<div class="text-muted" style="font-size: 0.65rem; margin-top: 2px;">{namespace}</div>'
    
    try:
        api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
        dep = client.AppsV1Api(api_client=api_client).read_namespaced_deployment(deployment_name, namespace)
        image = dep.spec.template.spec.containers[0].image
        short_image = image.split('/')[-1].split(':')[1] if ':' in image else "latest"
        ready = f"{dep.status.ready_replicas}/{dep.status.replicas}"
        
        content = f"""
            <div style="cursor: pointer;" hx-get="/api/describe/{cluster_id}/{ui_name}?t={ts}" 
                 hx-target="#modal-container" hx-swap="innerHTML">
                <div class="d-flex flex-column">
                    <span class="badge bg-light text-dark border text-truncate" style="max-width: 150px;" title="{image}">
                        {short_image}
                    </span>
                    <span class="small text-success mt-1">Ready: {ready}</span>
                </div>
            </div>
        """
        final_html = f"{cell_start}{content}{ns_badge}{cell_end}"
        CACHE["statuses"][cache_key] = final_html 
        return HTMLResponse(final_html)
    except Exception as e:
        err_msg = "Not Found" if "404" in str(e) else "Error"
        content = f'<span class="badge bg-danger bg-opacity-10 text-danger border border-danger" title="{deployment_name}">{err_msg}</span>'
        final_html = f"{cell_start}{content}{ns_badge}{cell_end}"
        CACHE["statuses"][cache_key] = final_html
        return HTMLResponse(final_html)

@app.get("/api/describe/{cluster_id}/{ui_name}", response_class=HTMLResponse)
def describe_service(cluster_id: str, ui_name: str, request: Request):
    data = load_db()
    svc = next((s for s in data["services"] if s['ui_name'] == ui_name), None)
    if not svc or cluster_id not in svc["clusters"]: return "Service mapping not found"
    
    details = svc["clusters"][cluster_id]
    service_name, namespace = details["deployment"], details["namespace"]
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster_info: return "Cluster not found"
    
    try:
        api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
        dep = client.AppsV1Api(api_client=api_client).read_namespaced_deployment(service_name, namespace)
        field = f"involvedObject.name={service_name},involvedObject.namespace={namespace},involvedObject.kind=Deployment"
        events = client.CoreV1Api(api_client=api_client).list_namespaced_event(namespace, field_selector=field).items
        events = sorted(events, key=lambda x: x.last_timestamp or x.event_time or x.metadata.creation_timestamp, reverse=True)
        return templates.TemplateResponse("describe_modal.html", {"request": request, "dep": dep, "events": events})
    except Exception as e:
        return f"<div class='alert alert-danger'>Could not fetch details: {str(e)}</div>"

@app.get("/api/scan-namespace/{cluster_id}", response_class=HTMLResponse)
def scan_namespace(cluster_id: str, namespace: str):
    data = load_db()
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster_info: return HTMLResponse("<div class='alert alert-danger'>Cluster config not found</div>")
    existing_ui_names = [s["ui_name"] for s in data["services"]]
    try:
        api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
        deployments = client.AppsV1Api(api_client=api_client).list_namespaced_deployment(namespace).items
        if not deployments: return HTMLResponse("<div class='alert alert-warning'>No deployments found.</div>")
        rows_html = ""
        for dep in deployments:
            d_name = dep.metadata.name
            suggested = guess_ui_name(d_name, existing_ui_names)
            rows_html += f"""<tr><td class="text-center align-middle"><input type="checkbox" name="selected_deployments" value="{d_name}" checked></td><td class="align-middle text-primary fw-bold">{d_name}<input type="hidden" name="deploy_{d_name}" value="{d_name}"></td><td class="align-middle"><input type="text" name="ui_name_{d_name}" value="{suggested}" class="form-control form-control-sm font-monospace text-dark"></td></tr>"""
        return HTMLResponse(f"""<form action="/import-bulk" method="post"><input type="hidden" name="cluster_id" value="{cluster_id}"><input type="hidden" name="namespace" value="{namespace}"><div class="table-responsive mb-3" style="max-height:400px;overflow-y:auto;"><table class="table table-sm table-hover border"><thead class="table-light sticky-top"><tr><th style="width:50px;">Import</th><th>K8s Deployment</th><th>UI Name</th></tr></thead><tbody>{rows_html}</tbody></table></div><div class="d-flex justify-content-end"><button type="submit" class="btn btn-success">Confirm Import</button></div></form>""")
    except Exception as e: return HTMLResponse(f"<div class='alert alert-danger'>Scan failed: {str(e)}</div>")

@app.post("/import-bulk")
async def import_bulk(request: Request):
    form_data = await request.form()
    cluster_id = form_data.get("cluster_id")
    namespace = form_data.get("namespace")
    selected = form_data.getlist("selected_deployments")
    data = load_db()
    for d_name in selected:
        ui_name = form_data.get(f"ui_name_{d_name}").strip()
        if not ui_name: continue
        entry = {"deployment": d_name, "namespace": namespace}
        existing = next((s for s in data['services'] if s['ui_name'] == ui_name), None)
        if existing: existing["clusters"][cluster_id] = entry
        else: data["services"].append({"ui_name": ui_name, "clusters": {cluster_id: entry}})
    save_db(data)
    CACHE["statuses"] = {} # Clear statuses to reflect new imports
    return RedirectResponse(url=f"/cluster/{cluster_id}", status_code=303)