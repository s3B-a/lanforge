from robyn import Request, Response, SubRouter, jsonify

from app.core import devices_store
from app.services import ssh_client

devices_router = SubRouter(__file__, prefix="/devices")

@devices_router.get("/", auth_required=True)
def list_devices(request: Request):
    return jsonify({"devices": devices_store.list_devices()})

@devices_router.get("/:device_id", auth_required=True)
def get_device(request: Request):
    device_id = request.path_params["device_id"]
    device = devices_store.get_device(device_id)
    if device is None:
        return Response(status_code=404, description="device not found", headers={})
    
    return jsonify(device)

@devices_router.post("/", auth_required=True)
def add_device(request: Request):
    body = request.json()
    try:
        device = devices_store.add_device(body)
    except ValueError as exc:
        return Response(status_code=409, description=str(exc), headers={})
    
    return jsonify(device)

@devices_router.patch("/:device_id", auth_required=True)
def patch_device(request: Request):
    device_id = request.path_params["device_id"]
    fields = request.json()
    device = devices_store.update_device(device_id, fields)
    if device is None:
        return Response(status_code=404, description="device not found", headers={})
    
    return jsonify(device)

@devices_router.delete("/:device_id", auth_required=True)
def delete_device(request: Request):
    device_id = request.path_params["device_id"]
    removed = devices_store.remove_device(device_id)
    if not removed:
        return Response(status_code=404, description="device not found", headers={})
    
    return jsonify({"removed": device_id})

@devices_router.get("/:device_id/stats", auth_required=True)
def device_stats(request: Request):
    device_id = request.path_params["device_id"]
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh":
        return Response(status_code=404, description="ssh device not found", headers={})

    try:
        stats = ssh_client.get_remote_stats(device)
    except Exception as exc:
        return Response(status_code=502, description=f"could not get stats: {exc}", headers={})

    return jsonify(stats)

@devices_router.post("/:device_id/heartbeat", auth_required=True)
def heartbeat(request: Request):
    device_id = request.path_params["device_id"]
    body = request.json()
    ip = body.get("ip") or request.ip_addr
    device = devices_store.record_heartbeat(device_id, ip)
    if device is None:
        return Response(status_code=404, description="device not found", headers={})
    
    return jsonify({"id": device_id, "last_ip": ip})