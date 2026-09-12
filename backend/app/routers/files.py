import base64

from robyn import Request, Response, SubRouter, jsonify

from app.core import devices_store
from app.services import ssh_client

files_router = SubRouter(__file__, prefix="/files")

def _ssh_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh":
        return None
    
    return device

@files_router.get("/:device_id/list", auth_required=True)
def list_dir(request: Request):
    device = _ssh_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="ssh device not found", headers={})

    path = request.query_params.to_dict().get("path", ["."])[0]
    entries = ssh_client.sftp_list(device, path)

    return jsonify({"path": path, "entries": entries})

@files_router.get("/:device_id/download", auth_required=True)
def download(request: Request):
    device = _ssh_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="ssh device not found", headers={})

    path = request.query_params.to_dict().get("path", [None])[0]
    if not path:
        return Response(status_code=400, description="missing 'path'", headers={})

    data = ssh_client.sftp_read(device, path)

    return jsonify({"path": path, "content_base64": base64.b64encode(data).decode()})


@files_router.post("/:device_id/upload", auth_required=True)
def upload(request: Request):
    device = _ssh_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="ssh device not found", headers={})

    body = request.json()
    path = body.get("path")
    content_b64 = body.get("content_base64")
    if not path or content_b64 is None:
        return Response(
            status_code=400, description="missing 'path' or 'content_base64'", headers={}
        )

    ssh_client.sftp_write(device, path, base64.b64decode(content_b64))

    return jsonify({"path": path, "written": True})