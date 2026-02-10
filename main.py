import os
import json
import time
import re
import shutil
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Request, UploadFile, File, Form, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from kubernetes import client, config
import boto3
from botocore.exceptions import ClientError

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- ROBUST DATA HANDLING (THE FIX) ---
DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "data.json")
CONFIG_DIR = "configs"

# Ensure directories exist on startup
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# Ensure data file exists (Prevents Docker crashes)
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({"clusters": [], "services": []}, f)

# --- GLOBAL STATE ---
CACHE = {
    "stats": {},      
    "statuses": {},   
    "timestamp": 0    
}

SSO_SESSION = {
    "access_token": None,
    "region": "us-east-1",
    "role_name": None,
    "cred_cache": {} 
}

# --- HELPERS ---
def load_db():
    try:
        with open(DATA_FILE, "r") as f:
            content = f.read()
            return json.loads(content) if content else {"clusters": [], "services": []}
    except: return {"clusters": [], "services": []}

def save_db(data):
    with open(DATA_FILE, "w") as f: json.dump(data, f, indent=4)

def guess_ui_name(deployment_name: str, existing_names: List[str]) -> str:
    if deployment_name in existing_names: return deployment_name
    matches = [name for name in existing_names if deployment_name.startswith(name)]
    if matches: return max(matches, key=len)
    return re.sub(r'-(blue|green|canary|prod|dev|staging|v\d+)$', '', deployment_name)

def get_last_updated():
    if CACHE["timestamp"] == 0: return "Never"
    return datetime.fromtimestamp(CACHE["timestamp"]).strftime("%H:%M:%S")

def extract_account_id(config_path: str) -> Optional[str]:
    """Robustly scans kubeconfig for an AWS Account ID."""
    try:
        with open(config_path, 'r') as f:
            content = f.read()
            match = re.search(r'arn:aws:eks:[a-z0-9-]+:(\d+):cluster', content)
            if match: return match.group(1)
            match_role = re.search(r'arn:aws:iam::(\d+):role', content)
            if match_role: return match_role.group(1)
    except: pass
    print(f"⚠️ Could NOT find Account ID in {config_path}")
    return None

def get_cluster_credentials(cluster_id: str):
    if not SSO_SESSION["access_token"]: return None
    
    data = load_db()
    cluster = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster: return None
    
    account_id = extract_account_id(cluster['config_path'])
    if not account_id: return None

    cached = SSO_SESSION["cred_cache"].get(account_id)
    if cached and cached['Expiration'].timestamp() > time.time(): return cached

    try:
        sso = boto3.client('sso', region_name=SSO_SESSION["region"])
        role_name = SSO_SESSION["role_name"] or "AdministratorAccess"
        creds = sso.get_role_credentials(
            roleName=role_name, accountId=account_id, accessToken=SSO_SESSION["access_token"]
        )
        pkg = {
            "AccessKeyId": creds['roleCredentials']['accessKeyId'],
            "SecretAccessKey": creds['roleCredentials']['secretAccessKey'],
            "SessionToken": creds['roleCredentials']['sessionToken'],
            "Expiration": datetime.fromtimestamp(creds['roleCredentials']['expiration'] / 1000.0)
        }
        SSO_SESSION["cred_cache"][account_id] = pkg
        return pkg
    except Exception as e:
        print(f"❌ Auth Failed: {e}")
        return None

class AWSContext:
    def __init__(self, cluster_id: str):
        self.cluster_id = cluster_id
        self.old_env = dict(os.environ)

    def __enter__(self):
        creds = get_cluster_credentials(self.cluster_id)
        if creds:
            os.environ["AWS_ACCESS_KEY_ID"] = creds["AccessKeyId"]
            os.environ["AWS_SECRET_ACCESS_KEY"] = creds["SecretAccessKey"]
            os.environ["AWS_SESSION_TOKEN"] = creds["SessionToken"]
            if SSO_SESSION["region"]:
                os.environ["AWS_DEFAULT_REGION"] = SSO_SESSION["region"]
                os.environ["AWS_REGION"] = SSO_SESSION["region"]
            if "AWS_PROFILE" in os.environ: del os.environ["AWS_PROFILE"]

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.environ.clear()
        os.environ.update(self.old_env)

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data = load_db()
    service_map = {}
    for svc in data["services"]:
        s_name = svc["ui_name"]
        if s_name not in service_map: service_map[s_name] = {}
        for c_id, det in svc["clusters"].items(): service_map[s_name][c_id] = det["namespace"]
    
    final_services = [{"ui_name": k, "cluster_map": v} for k, v in service_map.items()]
    is_logged_in = SSO_SESSION["access_token"] is not None

    return templates.TemplateResponse("index.html", {
        "request": request, "clusters": data["clusters"], "services": final_services, 
        "last_updated": get_last_updated(), "ts": int(time.time()), "logged_in": is_logged_in
    })

@app.get("/cluster/{cluster_id}", response_class=HTMLResponse)
async def cluster_detail(request: Request, cluster_id: str):
    data = load_db()
    cluster = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster: return HTMLResponse("Cluster not found", status_code=404)
    
    cluster_services = []
    for s in data["services"]:
        if cluster_id in s["clusters"]:
            cluster_services.append({
                "ui_name": s["ui_name"],
                "deployment": s["clusters"][cluster_id]["deployment"],
                "namespace": s["clusters"][cluster_id]["namespace"]
            })
            
    is_logged_in = SSO_SESSION["access_token"] is not None
    return templates.TemplateResponse("cluster_detail.html", {
        "request": request, "cluster": cluster, "services": cluster_services, 
        "last_updated": get_last_updated(), "ts": int(time.time()), "logged_in": is_logged_in
    })

@app.get("/api/cluster-stats/{cluster_id}")
def get_cluster_stats(cluster_id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if cluster_id in CACHE["stats"]: return HTMLResponse(CACHE["stats"][cluster_id])
    data = load_db()
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not cluster_info: return HTMLResponse("<div>Config Missing</div>")

    try:
        with AWSContext(cluster_id): 
            api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
            version = client.VersionApi(api_client=api_client).get_code().git_version
            nodes = len(client.CoreV1Api(api_client=api_client).list_node().items)
        html = f"""<div class="d-flex justify-content-between mt-3"><span class="badge bg-success bg-opacity-10 text-success border border-success">Online</span><span class="small fw-bold text-dark">{version}</span></div><div class="mt-2 small text-muted">Nodes: <strong>{nodes}</strong></div>"""
        CACHE["stats"][cluster_id] = html
        return HTMLResponse(html)
    except Exception: return HTMLResponse("""<div class="alert alert-danger py-1 px-2 mt-2 mb-0 small">Offline</div>""")

@app.get("/api/status/{cluster_id}/{ui_name}")
def get_k8s_status(cluster_id: str, ui_name: str, response: Response, ts: int = 0):
    cache_key = f"{cluster_id}_{ui_name}"
    if cache_key in CACHE["statuses"]: return HTMLResponse(CACHE["statuses"][cache_key])
    data = load_db()
    svc = next((s for s in data["services"] if s['ui_name'] == ui_name), None)
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if not svc or cluster_id not in svc["clusters"]: return HTMLResponse('<td class="status-cell align-middle"><span class="text-muted opacity-25">-</span></td>')
    details = svc["clusters"][cluster_id]

    try:
        with AWSContext(cluster_id):
            api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
            dep = client.AppsV1Api(api_client=api_client).read_namespaced_deployment(details["deployment"], details["namespace"])
        
        image = dep.spec.template.spec.containers[0].image
        short_image = image.split('/')[-1].split(':')[1] if ':' in image else "latest"
        ready = f"{dep.status.ready_replicas}/{dep.status.replicas}"
        content = f"""<div style="cursor: pointer;" hx-get="/api/describe/{cluster_id}/{ui_name}?t={ts}" hx-target="#modal-container" hx-swap="innerHTML"><div class="d-flex flex-column"><span class="badge bg-light text-dark border text-truncate" style="max-width: 150px;" title="{image}">{short_image}</span><span class="small text-success mt-1">Ready: {ready}</span></div></div>"""
        final = f'<td class="status-cell align-middle">{content}<div class="text-muted" style="font-size: 0.65rem;">{details["namespace"]}</div></td>'
        CACHE["statuses"][cache_key] = final
        return HTMLResponse(final)
    except Exception as e:
        return HTMLResponse(f'<td class="status-cell align-middle"><span class="badge bg-danger bg-opacity-10 text-danger border border-danger">Error</span></td>')

@app.get("/api/describe/{cluster_id}/{ui_name}", response_class=HTMLResponse)
def describe_service(cluster_id: str, ui_name: str, request: Request):
    data = load_db()
    svc = next((s for s in data["services"] if s['ui_name'] == ui_name), None)
    details = svc["clusters"][cluster_id]
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    try:
        with AWSContext(cluster_id):
            api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
            dep = client.AppsV1Api(api_client=api_client).read_namespaced_deployment(details["deployment"], details["namespace"])
            field = f"involvedObject.name={details['deployment']},involvedObject.namespace={details['namespace']},involvedObject.kind=Deployment"
            events = client.CoreV1Api(api_client=api_client).list_namespaced_event(details["namespace"], field_selector=field).items
        return templates.TemplateResponse("describe_modal.html", {"request": request, "dep": dep, "events": events})
    except Exception as e: return f"<div class='alert alert-danger'>{str(e)}</div>"

@app.get("/api/scan-namespace/{cluster_id}", response_class=HTMLResponse)
def scan_namespace(cluster_id: str, namespace: str):
    data = load_db()
    cluster_info = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    try:
        with AWSContext(cluster_id):
            api_client = config.new_client_from_config(config_file=cluster_info['config_path'])
            deployments = client.AppsV1Api(api_client=api_client).list_namespaced_deployment(namespace).items
        
        rows = ""
        existing = [s["ui_name"] for s in data["services"]]
        for dep in deployments:
            d_name = dep.metadata.name
            suggested = guess_ui_name(d_name, existing)
            rows += f"""<tr><td class="text-center align-middle"><input type="checkbox" name="selected_deployments" value="{d_name}" checked></td><td class="fw-bold text-primary">{d_name}<input type="hidden" name="deploy_{d_name}" value="{d_name}"></td><td><input type="text" name="ui_name_{d_name}" value="{suggested}" class="form-control form-control-sm"></td></tr>"""
        return HTMLResponse(f"""<form action="/import-bulk" method="post"><input type="hidden" name="cluster_id" value="{cluster_id}"><input type="hidden" name="namespace" value="{namespace}"><div class="table-responsive mb-3" style="max-height:400px;overflow-y:auto;"><table class="table table-sm table-hover border"><thead class="table-light sticky-top"><tr><th>Import</th><th>Deployment</th><th>UI Name</th></tr></thead><tbody>{rows}</tbody></table></div><div class="text-end"><button type="submit" class="btn btn-success">Confirm Import</button></div></form>""")
    except Exception as e: return HTMLResponse(f"<div class='alert alert-danger'>{str(e)}</div>")

@app.post("/refresh-all")
async def refresh_all(request: Request):
    CACHE["stats"] = {}
    CACHE["statuses"] = {}
    CACHE["timestamp"] = time.time()
    return RedirectResponse(url=request.headers.get("referer") or "/", status_code=303)

@app.post("/add-cluster")
async def add_cluster(alias: str = Form(...), file: UploadFile = File(...)):
    # Save to configs/ folder
    path = os.path.join(CONFIG_DIR, file.filename)
    with open(path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    data = load_db()
    data["clusters"].append({"id": alias.lower().replace(" ", "-"), "alias": alias, "config_path": path})
    save_db(data)
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete-cluster")
async def delete_cluster(cluster_id: str = Form(...)):
    data = load_db()
    # Remove config file (optional, but good for cleanup)
    cluster = next((c for c in data["clusters"] if c["id"] == cluster_id), None)
    if cluster and os.path.exists(cluster["config_path"]):
        os.remove(cluster["config_path"])
    
    data["clusters"] = [c for c in data["clusters"] if c["id"] != cluster_id]
    save_db(data)
    return RedirectResponse(url="/", status_code=303)

@app.post("/import-bulk")
async def import_bulk(request: Request):
    form = await request.form()
    c_id, ns = form.get("cluster_id"), form.get("namespace")
    data = load_db()
    for d_name in form.getlist("selected_deployments"):
        ui_name = form.get(f"ui_name_{d_name}").strip()
        if not ui_name: continue
        entry = {"deployment": d_name, "namespace": ns}
        existing = next((s for s in data['services'] if s['ui_name'] == ui_name), None)
        if existing: existing["clusters"][c_id] = entry
        else: data["services"].append({"ui_name": ui_name, "clusters": {c_id: entry}})
    save_db(data)
    CACHE["statuses"] = {}
    return RedirectResponse(url=f"/cluster/{c_id}", status_code=303)

@app.post("/unmap-service")
async def unmap_service(cluster_id: str = Form(...), ui_name: str = Form(...)):
    data = load_db()
    svc = next((s for s in data["services"] if s['ui_name'] == ui_name), None)
    if svc and cluster_id in svc["clusters"]:
        del svc["clusters"][cluster_id]
        if not svc["clusters"]: data["services"] = [s for s in data["services"] if s['ui_name'] != ui_name]
        save_db(data)
    CACHE["statuses"].pop(f"{cluster_id}_{ui_name}", None)
    return RedirectResponse(url=f"/cluster/{cluster_id}", status_code=303)

# --- AUTH ROUTES ---
@app.post("/auth/sso/start")
async def start_sso_login(start_url: str = Form(...), region: str = Form(...)):
    try:
        oidc = boto3.client('sso-oidc', region_name=region)
        client = oidc.register_client(clientName='k8s-central', clientType='public')
        auth = oidc.start_device_authorization(
            clientId=client['clientId'], clientSecret=client['clientSecret'], startUrl=start_url
        )
        return JSONResponse({
            "deviceCode": auth['deviceCode'], "userCode": auth['userCode'],
            "verificationUri": auth['verificationUriComplete'],
            "clientId": client['clientId'], "clientSecret": client['clientSecret'], "region": region
        })
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/auth/sso/poll")
async def poll_sso_token(device_code: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...), region: str = Form(...)):
    try:
        oidc = boto3.client('sso-oidc', region_name=region)
        token = oidc.create_token(
            clientId=client_id, clientSecret=client_secret,
            grantType='urn:ietf:params:oauth:grant-type:device_code', deviceCode=device_code
        )
        return JSONResponse({"accessToken": token['accessToken']})
    except ClientError as e:
        if e.response['Error']['Code'] == 'AuthorizationPendingException': return JSONResponse({"status": "pending"})
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/auth/sso/accounts")
async def list_accounts(access_token: str = Form(...), region: str = Form(...)):
    try:
        sso = boto3.client('sso', region_name=region)
        accounts = []
        paginator = sso.get_paginator('list_accounts')
        for page in paginator.paginate(accessToken=access_token): accounts.extend(page['accountList'])
        return JSONResponse({"accounts": accounts})
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/auth/sso/roles")
async def list_roles(access_token: str = Form(...), region: str = Form(...), account_id: str = Form(...)):
    try:
        sso = boto3.client('sso', region_name=region)
        roles = []
        paginator = sso.get_paginator('list_account_roles')
        for page in paginator.paginate(accessToken=access_token, accountId=account_id): roles.extend(page['roleList'])
        return JSONResponse({"roles": roles})
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/auth/sso/login")
async def final_login(access_token: str = Form(...), region: str = Form(...), role_name: str = Form(...)):
    SSO_SESSION["access_token"] = access_token
    SSO_SESSION["region"] = region
    SSO_SESSION["role_name"] = role_name
    SSO_SESSION["cred_cache"] = {} 
    return JSONResponse({"status": "success"})

@app.post("/auth/logout")
async def logout():
    SSO_SESSION["access_token"] = None
    return RedirectResponse("/", status_code=303)