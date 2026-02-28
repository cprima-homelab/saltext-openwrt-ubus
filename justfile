# saltext-uci development tasks (salt-master in WSL)

# MSYS_NO_PATHCONV prevents Git Bash from mangling /opt/... to C:/Program Files/Git/opt/...
export MSYS_NO_PATHCONV := "1"

wsl_dist := "salt-master"
pip := "/opt/saltstack/salt/bin/pip3"
pkg := "/mnt/d/github.com/cprima-homelab/saltext-uci"

# Install saltext-uci into salt-master's Python environment (editable)
install:
    wsl -d {{wsl_dist}} -- {{pip}} install -e {{pkg}}

# Reinstall (force, picks up renamed/new files)
reinstall:
    wsl -d {{wsl_dist}} -- {{pip}} install -e {{pkg}} --force-reinstall --no-deps

# Start salt-proxy for a device (foreground, ctrl-c to stop)
proxy-start device="austru":
    wsl -d {{wsl_dist}} -- salt-proxy --proxyid={{device}} -l info

# Start salt-proxy for a device (background daemon)
proxy-start-bg device="austru":
    wsl -d {{wsl_dist}} -- salt-proxy --proxyid={{device}} -l info -d

# Stop all salt-proxy processes
proxy-stop:
    -wsl -d {{wsl_dist}} -- pkill -f salt-proxy
    wsl -d {{wsl_dist}} -- bash -c 'rm -f /run/salt/proxy/minion_event_*.ipc'

# Stop a specific salt-proxy
proxy-stop-one device:
    -wsl -d {{wsl_dist}} -- pkill -f "salt-proxy --proxyid={{device}}"

# Quick connectivity test
ping device="austru":
    wsl -d {{wsl_dist}} -- salt {{device}} test.ping

# List accepted/pending minion keys
keys:
    wsl -d {{wsl_dist}} -- salt-key -L

# Accept a minion key
accept device:
    wsl -d {{wsl_dist}} -- salt-key -a {{device}} -y

# Run unit tests locally
test:
    uv run pytest tests/unit/ -v
