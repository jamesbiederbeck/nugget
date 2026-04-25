#!/bin/bash
# Setup script for nugget-server Docker deployment

set -e

echo "Setting up nugget-server Docker environment..."

# Check if docker/config/config.json exists
if [ ! -f "docker/config/config.json" ]; then
    echo "Creating config.json from template..."
    cp docker/config/config.json.template docker/config/config.json
    echo "✓ Created docker/config/config.json"
    echo ""
    echo "Please edit docker/config/config.json to configure your backend URL and other settings."
    echo ""
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    echo "ERROR: docker-compose or 'docker compose' command not found."
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "Setup complete! You can now run:"
if command -v docker-compose &> /dev/null; then
    echo "  docker-compose up -d          # Start the server"
    echo "  docker-compose logs -f        # View logs"
    echo "  docker-compose down           # Stop the server"
else
    echo "  docker compose up -d          # Start the server"
    echo "  docker compose logs -f        # View logs"
    echo "  docker compose down           # Stop the server"
fi
echo ""
echo "Web interface will be available at: http://localhost:8000"
