# Docker Setup for Nugget Server

This directory contains configuration and data for running nugget-server in Docker.

## Quick Start

1. **Start the server:**
   ```bash
   docker-compose up -d
   ```

2. **View logs:**
   ```bash
   docker-compose logs -f nugget-server
   ```

3. **Stop the server:**
   ```bash
   docker-compose down
   ```

## Configuration

Edit `docker/config/config.json` to customize settings:

- **api_url**: Set to your text-generation-webui or LLM backend URL
  - Use `http://host.docker.internal:5000` to connect to a service on your host
  - Use `http://backend-service:5000` if using docker networking with another container
- **model**: The model name expected by your backend
- **approval.rules**: Control tool execution permissions (shell is denied by default in Docker)

## Data Persistence

- **Sessions**: Stored in `docker/data/sessions/`
- **Memory**: Stored in `docker/data/memory.db`

These directories are mounted as volumes, so your data persists across container restarts.

## Network Configuration

### Connecting to a local backend

If you're running text-generation-webui on your host machine:

1. Use `api_url: "http://host.docker.internal:5000"` in config.json (Linux may need `--add-host=host.docker.internal:host-gateway`)
2. Or uncomment `network_mode: host` in docker-compose.yml

### Connecting to another container

If your LLM backend is also in Docker:

1. Uncomment the networks section in docker-compose.yml
2. Add your backend service to the same network
3. Use the service name as the hostname in api_url

## Accessing the Web Interface

Once running, access the web interface at:
```
http://localhost:8000
```

## Troubleshooting

**Can't connect to backend:**
- Verify your backend is running and accessible
- Check the api_url in config.json
- Review logs: `docker-compose logs nugget-server`

**Permission issues:**
- Ensure docker/config and docker/data directories are writable
- Check container logs for file system errors
