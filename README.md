# Swarm Manager

A Flask web application for managing Docker Swarm services.

## Running with Docker socket access

This application uses the Docker SDK and must be able to talk to the Docker daemon.
When running the container you should mount the host Docker socket into the container:

```bash
# Build container
docker build -t swarm-manager:latest .

# Deploy to swarm
docker stack deploy -c swarm-manager.tml swarm-manager

# Troubleshooting
docker service ls
docker service logs swarm-manager
```

