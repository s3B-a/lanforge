from robyn import Robyn, jsonify

from app.core.auth import TokenAuthHandler
from app.core.config import HUB_HOST, HUB_PORT
from app.routers import devices, files, llm, monitor, shell

app = Robyn(__file__)
app.configure_authentication(TokenAuthHandler())

app.include_router(devices.devices_router)
app.include_router(shell.shell_router)
app.include_router(files.files_router)
app.include_router(llm.llm_router)
app.include_router(monitor.monitor_router)

shell.register_websockets(app)
monitor.register_websockets(app)

@app.get("/health")
def health(request):
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.start(host=HUB_HOST, port=HUB_PORT)