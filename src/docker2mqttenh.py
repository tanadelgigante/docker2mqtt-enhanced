"""Listens to `docker system events` and sends container metrics to mqtt."""
import atexit
import datetime
import json
from os import environ
import paho.mqtt.client
import queue
import re
from socket import gethostname
from subprocess import run, Popen, PIPE
from threading import Thread
from time import sleep, time


DEBUG = environ.get('DEBUG', '1') == '1'
DESTROYED_CONTAINER_TTL = int(environ.get('DESTROYED_CONTAINER_TTL', 24 * 60 * 60))
HOMEASSISTANT_PREFIX = environ.get('HOMEASSISTANT_PREFIX', 'homeassistant')
DOCKER2MQTT_HOSTNAME = environ.get('DOCKER2MQTT_HOSTNAME', gethostname())
MQTT_CLIENT_ID = environ.get('MQTT_CLIENT_ID', 'docker2mqtt-enh')
MQTT_USER = environ.get('MQTT_USER', '')
MQTT_PASSWD = environ.get('MQTT_PASSWD', '')
MQTT_HOST = environ.get('MQTT_HOST', 'localhost')
MQTT_PORT = int(environ.get('MQTT_PORT', '1883'))
MQTT_TIMEOUT = int(environ.get('MQTT_TIMEOUT', '30'))
MQTT_TOPIC_PREFIX = environ.get('MQTT_TOPIC_PREFIX', 'docker')
MQTT_QOS = int(environ.get('MQTT_QOS', 1))
METRICS_UPDATE_INTERVAL = int(environ.get('METRICS_UPDATE_INTERVAL', '30'))  # seconds
DISCOVERY_TOPIC = f'{HOMEASSISTANT_PREFIX}/binary_sensor/{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}_{{}}/config'
WATCHED_EVENTS = ('create', 'destroy', 'die', 'pause', 'rename', 'start', 'stop', 'unpause')
MQTT_RECONNECT_DELAY = 300  # 5 minutes in seconds

known_containers = {}
pending_destroy_operations = {}
docker_events_cmd = ['docker', 'events', '-f', 'type=container', '--format', '{{json .}}']
docker_ps_cmd = ['docker', 'ps', '-a', '--format', '{{json .}}']
invalid_ha_topic_chars = re.compile(r'[^a-zA-Z0-9_-]')


def parse_memory_value(mem_str):
    """Convert memory string (e.g., '14.49MiB') to bytes."""
    units = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}
    num, unit = mem_str[:-3], mem_str[-3:]
    return float(num) * units[unit]


def format_size(size):
    """Format size in bytes to a human-readable format."""
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if size < 1024.0:
            return f"{size:.2f}{unit}"
        size /= 1024.0
    return f"{size:.2f}TiB"


def format_network_speed(speed):
    """Format network speed to a human-readable format."""
    return f"{speed:.2f} B/s"


def get_container_metrics(container_id):
    """Get detailed metrics for a container."""
    try:
        # Get container stats
        stats_cmd = ['docker', 'stats', container_id, '--no-stream', '--format', '{{json .}}']
        stats = json.loads(run(stats_cmd, stdout=PIPE, text=True).stdout)

        # Get container inspect info
        inspect_cmd = ['docker', 'inspect', container_id]
        inspect = json.loads(run(inspect_cmd, stdout=PIPE, text=True).stdout)[0]

        # Parse CPU stats
        cpu_percent = float(stats.get('CPUPerc', '0%').strip('%'))
        cpu_percent = f"{cpu_percent:.2f}%"  # Limita a 2 decimali
        cpu_cores = str(len(inspect['HostConfig']['CpusetCpus'].split(','))) if inspect['HostConfig']['CpusetCpus'] else '0'

        # Parse memory stats
        mem_usage = parse_memory_value(stats.get('MemUsage', '0 / 0').split('/')[0].strip())
        formatted_mem_usage = f"{mem_usage:.1f} B" if mem_usage >= 10 else f"{mem_usage:.2f} B"
        mem_limit_str = stats.get('MemUsage', '0 / 0').split('/')[1].strip().split()[0]
        mem_percent = float(stats.get('MemPerc', '0%').strip('%'))
        mem_percent = f"{mem_percent:.2f}%"  # Limita a 2 decimali

        # Parse network stats
        net_stats = stats.get('NetIO', '0B / 0B').split(' / ')
        net_in = net_stats[0].rstrip('B')
        net_out = net_stats[1].rstrip('B')

        # Calculate network speed (requires two measurements)
        # This is simplified - in production you'd want to track previous measurements
        net_speed_in = "0 B/s"  # Would need delta calculation
        net_speed_out = "0 B/s"  # Would need delta calculation

        # Get health status
        health_status = inspect['State'].get('Health', {}).get('Status', 'none')

        # Get uptime
        # Converti l'uptime in formato leggibile
        started_at = datetime.datetime.strptime(
            inspect['State']['StartedAt'].split('.')[0],
            '%Y-%m-%dT%H:%M:%S'
        )
        uptime_seconds = (datetime.datetime.utcnow() - started_at).total_seconds()
        uptime_human = str(datetime.timedelta(seconds=int(uptime_seconds)))

        return {
            'cpu_percent': cpu_percent,
            'cpu_cores': cpu_cores,
            'memory_usage': formatted_mem_usage,
            'memory_limit': mem_limit_str,
            'memory_percent': mem_percent,
            'net_in_total': net_in,
            'net_out_total': net_out,
            'net_in_speed': net_speed_in,
            'net_out_speed': net_speed_out,
            'health_status': health_status,
            'uptime': str(int(uptime_seconds)),
            'uptime_h': uptime_human,
            'state': inspect['State']['Status']
        }
    except Exception as e:
        print(f"Error getting metrics for container {container_id}: {e}")
        return {}


def update_metrics():
    """Update metrics for all known containers periodically."""
    while True:
        for container_name in known_containers.copy().items():
            try:
                # Get container ID using docker ps
                ps_cmd = ['docker', 'ps', '-a', '--filter', f'name=^/{container_name}$', '--format', '{{.ID}}']
                container_id = run(ps_cmd, stdout=PIPE, text=True).stdout.strip()
                
                if container_id:
                    metrics = get_container_metrics(container_id)
                    known_containers[container_name].update(metrics)
                    mqtt_send(
                        f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{container_name}',
                        json.dumps(known_containers[container_name]),
                        retain=True
                    )
            except Exception as e:
                print(f"Error updating metrics for {container_name}: {e}")
        
        sleep(METRICS_UPDATE_INTERVAL)


# Existing functions remain the same
@atexit.register
def mqtt_disconnect():
    mqtt.publish(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/status', 'offline', qos=MQTT_QOS, retain=True)
    mqtt.disconnect()
    sleep(1)
    mqtt.loop_stop()


def on_disconnect(client, userdata, rc):
    """Callback for when the client disconnects from the MQTT broker."""
    print(f"Disconnected from MQTT broker with code: {rc}")
    if rc != 0:
        print("Unexpected disconnection. Will attempt to reconnect...")

def mqtt_connect_with_retry(mqtt_client):
    """Attempts to connect to MQTT broker with retry mechanism."""
    connected = False
    while not connected:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, MQTT_TIMEOUT)
            connected = True
            print("Successfully connected to MQTT broker")
            mqtt_send(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/status', 'online', retain=True)
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
            print(f"Retrying in {MQTT_RECONNECT_DELAY} seconds...")
            sleep(MQTT_RECONNECT_DELAY)

def mqtt_send(topic, payload, retain=False):
    """Send message to MQTT broker with reconnection handling."""
    try:
        if DEBUG:
            print(f'Sending to MQTT: {topic}: {payload}')
        result = mqtt.publish(topic, payload=payload, qos=MQTT_QOS, retain=retain)
    except Exception as e:
        print(f'MQTT Publish Failed: {e}')
        print("Attempting to reconnect...")
        mqtt_connect_with_retry(mqtt)
        # Retry the publish after reconnection
        try:
            mqtt.publish(topic, payload=payload, qos=MQTT_QOS, retain=retain)
        except Exception as e:
            print(f'MQTT Publish Failed after reconnection attempt: {e}')


def register_container(container_entry):
    container_name = f"{DOCKER2MQTT_HOSTNAME}_{container_entry['name']}"
    known_containers[container_entry['name']] = container_entry
    registration_topic = DISCOVERY_TOPIC.format(invalid_ha_topic_chars.sub('_', container_name))
    registration_packet = {
        'name': f"{MQTT_TOPIC_PREFIX.title()} {container_name}",
        'unique_id': f'{MQTT_TOPIC_PREFIX}_{container_name}',
        'availability_topic': f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/status',
        'payload_available': 'online',
        'payload_not_available': 'offline',
        'state_topic': f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{container_entry["name"]}',
        'value_template': '{{ value_json.state }}',
        'payload_on': 'on',
        'payload_off': 'off',
        'device_class': 'connectivity',
        'json_attributes_topic': f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{container_entry["name"]}',
    }
    mqtt_send(registration_topic, json.dumps(registration_packet), retain=True)
    # Initialize container with metrics
    try:
        ps_cmd = ['docker', 'ps', '-a', '--filter', f'name=^/{container_entry["name"]}$', '--format', '{{.ID}}']
        container_id = run(ps_cmd, stdout=PIPE, text=True).stdout.strip()
        if container_id:
            metrics = get_container_metrics(container_id)
            container_entry.update(metrics)
    except Exception as e:
        print(f"Error initializing metrics for {container_entry['name']}: {e}")
    
    mqtt_send(
        f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{container_entry["name"]}',
        json.dumps(container_entry),
        retain=True
    )


def readline_thread():
    """Run docker events and continually read lines from it."""
    with Popen(docker_events_cmd, stdout=PIPE, text=True) as proc:
        while True:
            docker_events.put(proc.stdout.readline())


if __name__ == '__main__':
    # Setup MQTT
    mqtt = paho.mqtt.client.Client()
    mqtt.username_pw_set(username=MQTT_USER, password=MQTT_PASSWD)
    mqtt.will_set(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/status', 'offline', qos=MQTT_QOS, retain=True)
    mqtt.on_disconnect = on_disconnect
    
    # Initial connection with retry
    mqtt_connect_with_retry(mqtt)
    mqtt.loop_start()
    
    mqtt_send(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/status', 'online', retain=True)

    # Register containers with HA
    docker_ps = run(docker_ps_cmd, stdout=PIPE, text=True)
    for line in docker_ps.stdout.splitlines():
        container_status = json.loads(line)
        
        if 'Paused' in container_status['Status']:
            status_str = 'paused'
            state_str = 'off'
        elif 'Up' in container_status['Status']:
            status_str = 'running'
            state_str = 'on'
        else:
            status_str = 'stopped'
            state_str = 'off'
        
        register_container({
            'name': container_status['Names'],
            'image': container_status['Image'],
            'status': status_str,
            'state': state_str
        })

    # Start the metrics update thread
    metrics_thread = Thread(target=update_metrics, daemon=True)
    metrics_thread.start()

    # Start the docker events thread
    docker_events = queue.Queue()
    docker_events_t = Thread(target=readline_thread, daemon=True)
    docker_events_t.start()

    # Main event loop remains largely the same
    while True:
        # Remove any destroyed containers that have passed the TTL
        for container, destroyed_at in pending_destroy_operations.copy().items():
            if time() - destroyed_at > DESTROYED_CONTAINER_TTL:
                print(f'Removing container {container} from MQTT.')
                registration_topic = DISCOVERY_TOPIC.format(invalid_ha_topic_chars.sub('_', container))
                mqtt_send(registration_topic, '', retain=True)
                mqtt_send(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{container}', '', retain=True)
                del(pending_destroy_operations[container])

        try:
            line = docker_events.get(timeout=1)
        except queue.Empty:
            continue
 
        event = json.loads(line)
        if event['status'] not in WATCHED_EVENTS:
            continue

        container = event['Actor']['Attributes']['name']

        if event['status'] == 'create':
            print(f'Container {container} has been created.')
            if container in pending_destroy_operations:
                print(f'Removing pending delete for {container}.')
                del(pending_destroy_operations[container])

            register_container({
                'name': container,
                'image': event['from'],
                'status': 'created',
                'state': 'off'
            })

        elif event['status'] == 'destroy':
            print(f'Container {container} has been destroyed.')
            pending_destroy_operations[container] = time()
            known_containers[container]['status'] = 'destroyed'
            known_containers[container]['state'] = 'off'

        elif event['status'] == 'die':
            print(f'Container {container} has stopped.')
            known_containers[container]['status'] = 'stopped'
            known_containers[container]['state'] = 'off'

        elif event['status'] == 'pause':
            print(f'Container {container} has paused.')
            known_containers[container]['status'] = 'paused'
            known_containers[container]['state'] = 'off'

        elif event['status'] == 'rename':
            old_name = event['Actor']['Attributes']['oldName']
            if old_name.startswith('/'):
                old_name = old_name[1:]
            print(f'Container {old_name} renamed to {container}.')
            mqtt_send(f'{HOMEASSISTANT_PREFIX}/binary_sensor/{MQTT_TOPIC_PREFIX}/{old_name}/config', '', retain=True)
            mqtt_send(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{old_name}', '', retain=True)
            register_container({
                'name': container,
                'image': known_containers[old_name]['image'],
                'status': known_containers[old_name]['status'],
                'state': known_containers[old_name]['state']
            })
            del(known_containers[old_name])

        elif event['status'] == 'start':
            print(f'Container {container} has started.')
            known_containers[container]['status'] = 'running'
            known_containers[container]['state'] = 'on'

        elif event['status'] == 'unpause':
            print(f'Container {container} has unpaused.')
            known_containers[container]['status'] = 'running'
            known_containers[container]['state'] = 'on'

        else:
            continue

        mqtt_send(f'{MQTT_TOPIC_PREFIX}/{DOCKER2MQTT_HOSTNAME}/{container}', json.dumps(known_containers[container]), retain=True)
