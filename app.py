# Importer de ting vi skal bruge
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin
import docker
import uuid
from datetime import datetime

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


# Dashboard
@app.route("/")
@login_required
def dashboard():
    client = docker.from_env()
    services = client.services.list()
    containers = client.containers.list(all=True)
# Her samler den alle tasks som er lavet per service
    service_data = []
    tasks_dict = {}  

    for s in services:
        try:
	# her gemmer den tasks per service navn
            tasks = s.tasks()
            tasks_dict[s.name] = tasks 

            status = "running"
            if not any(t["Status"]["State"] == "running" for t in tasks):
                status = "stopped"

            created = s.attrs.get("CreatedAt", "")
            created_time = created.split(".")[0] if created else "ukendt"

            service_data.append({
                "id": s.id,
                "name": s.name,
                "status": status,
                "created": created_time,
                "replicas": s.attrs["Spec"]["Mode"].get("Replicated", {}).get("Replicas", 0)
            })
        except Exception:
            pass 

    return render_template("dashboard.html", services=service_data, containers=containers, tasks=tasks_dict)


# Start service igen
# Denne route starter en service ved at sætte replicas = 1
@app.route("/service/start/<service_id>")
@login_required
def service_start(service_id):
    client = docker.from_env()

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


@app.route("/service/stop/<service_id>")
@login_required
def service_stop(service_id):
    client = docker.from_env()

    try:
        service = client.services.get(service_id)
        spec = service.attrs["Spec"]

        # Sætter antal replicas til 0 for at stoppe servicen
        mode = spec.get("Mode", {})
        if "Replicated" in mode:
            mode["Replicated"]["Replicas"] = 0
        else:
            mode = {"Replicated": {"Replicas": 0}}

        # Opdaterer servicen så den stopper
        service.update(
            taskTemplate=spec.get("TaskTemplate"),
            name=spec.get("Name"),
            labels=spec.get("Labels", {}),
            mode=mode,
            networks=spec.get("Networks", []),
            endpoint_spec=spec.get("EndpointSpec", {})
        )

        flash("Service stoppet", "info")

    except Exception as e:
        flash(f"Fejl: {e}", "danger")

    return redirect(url_for("dashboard"))





# Slet service
@app.route("/service/delete/<service_id>")
@login_required
def service_delete(service_id):
    client = docker.from_env()
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

        if image == "custom":
            image = request.form.get("custom_image")

        deploy_results[task_id] = {"status": "running", "message": "Deployment startet..."}

        try:
            client = docker.from_env()
            client.services.create(
                image, 
                name=name, 
                mode={"Replicated": {"Replicas": replicas}},
                task_template={"Placement": {"Constraints": [f"node.labels.site == {site}"]}}
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
