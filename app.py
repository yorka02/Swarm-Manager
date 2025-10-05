# Importer de ting vi skal bruge
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin
import docker
import uuid
from datetime import datetime, timezone, timedelta

# Starter Flask app
app = Flask(__name__)
app.secret_key = "Sde12345" 

# Login system setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Dummy bruger 
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Vores admin login bruger 
users = {"admin": {"password": "Sde12345"}}

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)


# ---------- ROUTES ----------
# Gemmer deploy resultater
deploy_results = {}


# Login side hvor den tjekker vores dummy user
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username in users and users[username]["password"] == password:
            user = User(username)
            login_user(user)
            return redirect(url_for("dashboard"))
        else:
            flash("Forkert login", "danger")
    return render_template("login.html")

# Logout
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# This function is definitely vibe coded (¬‿¬)
def format_docker_timestamp(ts: str) -> str:
    """Parse Docker/RFC3339 nanosecond timestamp like
    2025-10-04T18:40:32.976483032Z and return a nicer string in CET.
    Falls back to the original string on parse error.
    """

    CET = timezone(timedelta(hours=1), name="CET")
    if not ts:
        return ""
    try:
        if ts.endswith('Z'):
            ts = ts[:-1]
        if '.' in ts:
            base, frac = ts.split('.', 1)
            frac = ''.join(ch for ch in frac if ch.isdigit())
            frac = (frac + '000000')[:6]
            ts_fixed = f"{base}.{frac}"
            dt = datetime.fromisoformat(ts_fixed)
        else:
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_cet = dt.astimezone(CET)
        return dt_cet.strftime('%Y-%m-%d %H:%M:%S %Z')
    except Exception:
        return ts

# Class for controlling the swarm
class SwarmManager:
    def __init__(self):
        self.client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    
    def list_services(self):
        return self.client.services.list()

    def list_containers(self):
        return self.client.containers.list(all=True)

    def get_container(self, container_id):
        """Return basic container info as a tuple:
        (id, name, status, health, image, created)
        """
        container = self.client.containers.get(container_id)
        container_attrs = container.attrs
        container_id = container.id
        container_name = container.name
        container_status = getattr(container, 'status', container_attrs.get('State', {}).get('Status'))
        container_health = getattr(container, 'health', container_attrs.get('State', {}).get('Health', {}).get('Status'))
        container_image = container_attrs.get('Config', {}).get('Image')
        container_created_at = format_docker_timestamp(container_attrs.get('Created'))
        return (container_id, container_name, container_status, container_health, container_image, container_created_at)

    def get_service(self, service_id):
        """Return common service fields as a tuple:
        (name, image, id, replicas, labels, created_at, updated_at)
        
        Example usage:
            manager = SwarmManager()
            service_name, service_image, service_id, service_replicas, service_labels, service_created_at, service_updated_at = manager.get_service("j22d6gjdaio1")
        """
        service = self.client.services.get(service_id)
        service_attrs = service.attrs
        service_name = service.name
        service_id = service.id
        service_image = service.attrs.get("Spec", {}).get("TaskTemplate", {}).get("ContainerSpec", {}).get("Image")
        service_replicas = service.attrs.get("Spec", {}).get("Mode", {}).get("Replicated", {}).get("Replicas", 0)
        service_labels = service.attrs.get("Spec", {}).get("Labels", {})
        service_created_at = format_docker_timestamp(service_attrs.get("CreatedAt", ""))
        service_updated_at = format_docker_timestamp(service_attrs.get("UpdatedAt", ""))
        return (service_name, service_image, service_id, service_replicas, service_labels, service_created_at, service_updated_at)

    def start_service(self, service_id):
        service = self.get_service(service_id)
        spec = service.attrs["Spec"]
        mode = spec.get("Mode", {})
        if "Replicated" in mode:
            mode["Replicated"]["Replicas"] = 1
        else:
            mode = {"Replicated": {"Replicas": 1}}
        service.update(
            taskTemplate=spec.get("TaskTemplate"),
            name=spec.get("Name"),
            labels=spec.get("Labels", {}),
            mode=mode,
            networks=spec.get("Networks", []),
            endpoint_spec=spec.get("EndpointSpec", {})
        )

    def stop_service(self, service_id):
        service = self.get_service(service_id)
        spec = service.attrs["Spec"]
        mode = spec.get("Mode", {})
        if "Replicated" in mode:
            mode["Replicated"]["Replicas"] = 0
        else:
            mode = {"Replicated": {"Replicas": 0}}
        service.update(
            taskTemplate=spec.get("TaskTemplate"),
            name=spec.get("Name"),
            labels=spec.get("Labels", {}),
            mode=mode,
            networks=spec.get("Networks", []),
            endpoint_spec=spec.get("EndpointSpec", {})
        )

    def delete_service(self, service_id):
        service = self.get_service(service_id)
        service.remove()

    def deploy_service(self, name, image, replicas, site):
        """Deploy a new service with given parameters.
        Example: deploy_service("web", "nginx:latest", 3, "a")
        """
        self.client.services.create(
            image, 
            name=name, 
            mode={"Replicated": {"Replicas": replicas}},
            container_labels={"node.labels.site": site},
            constraints=["node.role == worker"]
        )
# Create an instance of SwarmManager
swarm_manager = SwarmManager()

# Dashboard
@app.route("/")
@login_required
def dashboard():
    # Get all services and containers using SwarmManager instance
    services = swarm_manager.list_services()
    containers = swarm_manager.list_containers()

    for s in services:
        service_name, service_image, service_id, service_replicas, service_labels, service_created_at, service_updated_at = swarm_manager.get_service(s.id)

        # Hide traefik and swarm-manager services from dashboard
        if service_name.startswith("traefik-site-") or service_name == "swarm-manager_web":
            continue
        
        # Get tasks/containers for the service
        for container in s.tasks():
            container_id, container_name, container_status, container_health, container_image, container_created_at = swarm_manager.get_container(container.get('Status', {}).get('ContainerStatus', {}).get('ContainerID', ''))

            s.container_data = {
                "id": container_id,
                "name": container_name,
                "status": container_status,
                "health": container_health,
                "image": container_image,
                "created": container_created_at
            }

        #  Format service data
        service_data = {
            "id": service_id,
            "name": service_name,
            "image": service_image or "unknown",
            "replicas": service_replicas,
            "labels": service_labels,
            "created": service_created_at or "unknown",
            "updated": service_updated_at or "unknown"
        }

    # Her samler den alle tasks som er lavet per service
    #service_data = []
    #tasks_dict = {}  

    # for s in services:
    #     # Filter out containers with name traefik-site-* and swarm-manager_web
    #     names = s.name
    #     if names.startswith("traefik-site-") or names == "swarm-manager_web":
    #         continue
    #     try:
    #         # her gemmer den tasks per service navn
    #         tasks = s.tasks()
    #         tasks_dict[s.name] = tasks 

    #         if any(t["Status"]["State"] == "running" for t in tasks):
    #             status = "running"

    #         if any(t["Status"]["State"] == "stopped" for t in tasks):
    #             status = "stopped"

    #         if any(t["Status"]["State"] == "preparing" for t in tasks):
    #             status = "preparing"

    #         if any(t["Status"]["State"] == "starting" for t in tasks):
    #             status = "starting"

    #         else:
    #             status = "unknown"

    #         created = s.attrs.get("CreatedAt", "")
    #         created_time = created.split(".")[0] if created else "ukendt"

    #         # Extract image from service spec (TaskTemplate -> ContainerSpec -> Image)
    #         image = None
    #         try:
    #             image = s.attrs.get("Spec", {}).get("TaskTemplate", {}).get("ContainerSpec", {}).get("Image")
    #         except Exception:
    #             image = None

    #         # Extract site label from service spec labels or from TaskTemplate ContainerSpec labels
    #         site_label = None
    #         try:
    #             spec_labels = s.attrs.get("Spec", {}).get("Labels", {}) or {}
    #             container_labels = s.attrs.get("Spec", {}).get("TaskTemplate", {}).get("ContainerSpec", {}).get("Labels", {}) or {}
    #             # prefer service-level label 'site' or 'node.labels.site'
    #             site_label = spec_labels.get("site") or spec_labels.get("node.labels.site") or container_labels.get("site") or container_labels.get("node.labels.site")
    #         except Exception:
    #             site_label = None

    #         service_data.append({
    #             "id": s.id,
    #             "name": s.name,
    #             "status": status,
    #             "created": created_time,
    #             "replicas": s.attrs["Spec"]["Mode"].get("Replicated", {}).get("Replicas", 0),
    #             "image": image or "unknown",
    #             "site": site_label.upper() or "-"
    #         })
    #     except Exception:
    #         pass 

    return render_template("dashboard.html", services=service_data, tasks=containers)


# Start service igen
# Denne route starter en service ved at sætte replicas = 1
@app.route("/service/start/<service_id>")
@login_required
def service_start(service_id):
    client = docker.DockerClient(base_url='unix://var/run/docker.sock')

    try:
        service = client.services.get(service_id)
        spec = service.attrs["Spec"]

        # Sætter antal replicas til 1 for at starte servicen
        mode = spec.get("Mode", {})
        if "Replicated" in mode:
            mode["Replicated"]["Replicas"] = 1
        else:
            mode = {"Replicated": {"Replicas": 1}}

        # Opdaterer servicen med den nye konfiguration
        service.update(
            taskTemplate=spec.get("TaskTemplate"),
            name=spec.get("Name"),
            labels=spec.get("Labels", {}),
            mode=mode,
            networks=spec.get("Networks", []),
            endpoint_spec=spec.get("EndpointSpec", {})
        )

        flash("Service startet", "success")

    except Exception as e:
        flash(f"Fejl: {e}", "danger")

    return redirect(url_for("dashboard"))

# This function does not currently work!
@app.route("/service/stop/<service_id>")
@login_required
def service_stop(service_id):
    flash("Denne funktion virker desværre ikke endnu.", "warning")
    return redirect(url_for("dashboard"))
    # client = docker.DockerClient(base_url='unix://var/run/docker.sock')

    # try:
    #     service = client.services.get(service_id)
    #     spec = service.attrs["Spec"]

    #     # Sætter antal replicas til 0 for at stoppe servicen
    #     mode = spec.get("Mode", {})
    #     if "Replicated" in mode:
    #         mode["Replicated"]["Replicas"] = 0
    #     else:
    #         mode = {"Replicated": {"Replicas": 0}}

    #     # Opdaterer servicen så den stopper
    #     service.update(
    #         taskTemplate=spec.get("TaskTemplate"),
    #         name=spec.get("Name"),
    #         labels=spec.get("Labels", {}),
    #         mode=mode,
    #         networks=spec.get("Networks", []),
    #         endpoint_spec=spec.get("EndpointSpec", {})
    #     )

    #     flash("Service stoppet", "info")

    # except Exception as e:
    #     flash(f"Fejl: {e}", "danger")

    # return redirect(url_for("dashboard"))





# Slet service
@app.route("/service/delete/<service_id>")
@login_required
def service_delete(service_id):
    client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    try:
        service = client.services.get(service_id)
        service.remove()
        flash("Service slettet", "warning")
    except Exception as e:
        flash(f"Fejl: {e}", "danger")
    return redirect(url_for("dashboard"))




# Deploy ny service
@app.route("/deploy", methods=["GET", "POST"])
@login_required
def deploy():
    if request.method == "POST":
        task_id = str(uuid.uuid4())
        name = request.form["name"]
        replicas = int(request.form["replicas"])
        image = request.form.get("image")
        site = request.form.get("site")

        if image == "custom":
            image = request.form.get("custom_image")

        deploy_results[task_id] = {"status": "running", "message": "Deployment startet..."}

        try:
            client = docker.DockerClient(base_url='unix://var/run/docker.sock')
            client.services.create(
                image, 
                name=name, 
                mode={"Replicated": {"Replicas": replicas}},
                #task_template={"Placement": {"Constraints": [f"node.labels.site == {site}"]}},
                container_labels={"node.labels.site": site},
                constraints=["node.role == worker"]
            )
            deploy_results[task_id] = {"status": "success", "message": f"Service {name} deployed"}
        except Exception as e:
            deploy_results[task_id] = {"status": "error", "message": f"Fejl: {e}"}

        return redirect(url_for("deploy_status", task_id=task_id))

    return render_template("deploy.html")

# Status side for deploy
@app.route("/deploy/status/<task_id>")
@login_required
def deploy_status(task_id):
    result = deploy_results.get(task_id, {"status": "unknown", "message": "Ingen info"})
    return render_template("deploy_status.html", result=result, task_id=task_id)

# appen køre her
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
