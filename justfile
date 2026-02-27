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

# Start salt-proxy (foreground, ctrl-c to stop)
proxy-start:
    wsl -d {{wsl_dist}} -- salt-proxy --proxyid=austru -l info

# Stop salt-proxy and clean up stale state
proxy-stop:
    -wsl -d {{wsl_dist}} -- pkill -f salt-proxy
    wsl -d {{wsl_dist}} -- bash -c 'rm -f /run/salt/proxy/minion_event_*.ipc /var/run/salt/austru/salt-minion.pid'

# Quick connectivity test
ping:
    wsl -d {{wsl_dist}} -- salt austru test.ping

# Run unit tests locally
test:
    uv run pytest tests/unit/ -v
