# Docker2MQTT Enhanced

This project is a fork of [docker2mqtt](https://github.com/skullydazed/docker2mqtt) that enhances container monitoring capabilities by adding detailed metrics and improving Home Assistant integration.

## Features

- **Enhanced Container Metrics**:
  - CPU usage percentage and core count
  - Memory usage and limits
  - Network I/O statistics
  - Container health status
  - Uptime tracking
  - Container state monitoring

- **Improved Home Assistant Integration**:
  - Automatic device discovery
  - Rich container status information
  - Real-time metric updates
  - Retained MQTT messages for better state persistence

- **Multi-Architecture Support**:
  - Standard amd64/x86_64 support
  - ARM support (armhf/armv7)
  - ARMv6 support (Raspberry Pi 1 and Zero)

## Configuration

Configuration is done through environment variables:

```yaml
DESTROYED_CONTAINER_TTL: 86400      # How long to retain destroyed container info (seconds)
DOCKER2MQTT_HOSTNAME: my_docker_host # Host identifier
HOMEASSISTANT_PREFIX: homeassistant # Home Assistant MQTT prefix
MQTT_CLIENT_ID: docker2mqtt         # MQTT client identifier
MQTT_HOST: mosquitto               # MQTT broker hostname
MQTT_PORT: 1883                    # MQTT broker port
MQTT_USER: username                # MQTT username
MQTT_PASSWD: password              # MQTT password
MQTT_TIMEOUT: 30                   # MQTT connection timeout
MQTT_TOPIC_PREFIX: docker          # MQTT topic prefix
MQTT_QOS: 1                        # MQTT QoS level
METRICS_UPDATE_INTERVAL: 10        # Metrics update frequency (seconds)
```

## Installation

### Using Docker Compose

1. Clone this repository
2. Copy the `docker-compose.yaml` file and adjust the environment variables
3. Run:

```bash
docker-compose up -d
```

### Manual Docker Run

```bash
docker run -d \
  --name docker2mqtt-enh \
  -e MQTT_HOST=your_mqtt_host \
  -e MQTT_USER=your_username \
  -e MQTT_PASSWD=your_password \
  -v /var/run/docker.sock:/var/run/docker.sock \
  docker2mqtt-enh
```


## Main Improvements Over Original

- Added detailed container metrics (CPU, memory, network)
- Improved MQTT message retention and state handling
- Enhanced Home Assistant integration with auto-discovery
- Added multi-architecture support (amd64, armhf, armv6)
- Real-time metric updates with configurable intervals
- Better error handling and logging
- Container health status monitoring
- Uptime tracking

## License

This project follows the same license as the original docker2mqtt project.

