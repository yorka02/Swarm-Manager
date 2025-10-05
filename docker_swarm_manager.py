import docker
class SwarmManager:
    # 
    def __init__(self):
        self.client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    
    def list_services(self):
        return self.client.services.list()

    def get_service(self, service_id):
        return self.client.services.get(service_id)

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
        self.client.services.create(
            image, 
            name=name, 
            mode={"Replicated": {"Replicas": replicas}},
            container_labels={"node.labels.site": site},
            constraints=["node.role == worker"]
        )

        SwarmManager.list_services(self)