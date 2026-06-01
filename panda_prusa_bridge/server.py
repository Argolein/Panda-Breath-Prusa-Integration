from __future__ import annotations

import base64
import hashlib
import json
import logging
import socketserver
import time
from http.server import BaseHTTPRequestHandler
from typing import Any

from panda_prusa_bridge.config import BridgeConfig
from panda_prusa_bridge.prusalink import BridgeStatus, PrusaLinkClient


LOGGER = logging.getLogger(__name__)
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class PandaBridgeService:
    def __init__(self, prusalink_client: PrusaLinkClient):
        self._prusalink_client = prusalink_client

    def handle_jsonrpc(self, message: dict[str, Any]) -> dict[str, Any] | None:
        message_id = message.get("id")
        method = message.get("method")

        if method == "printer.objects.query":
            params = message.get("params", {})
            objects = params.get("objects", {})
            return {
                "jsonrpc": "2.0",
                "result": self.build_query_result(objects),
                "id": message_id,
            }

        if method == "printer.objects.subscribe":
            params = message.get("params", {})
            objects = params.get("objects", {})
            return {
                "jsonrpc": "2.0",
                "result": self.build_query_result(objects),
                "id": message_id,
            }

        if method == "server.info":
            return {
                "jsonrpc": "2.0",
                "result": self.build_server_info(),
                "id": message_id,
            }

        if method == "printer.info":
            return {
                "jsonrpc": "2.0",
                "result": self.build_printer_info(),
                "id": message_id,
            }

        if method == "printer.objects.list":
            return {
                "jsonrpc": "2.0",
                "result": self.build_objects_list(),
                "id": message_id,
            }

        if message_id is None:
            LOGGER.info("Ignoring notification method=%s", method)
            return None

        LOGGER.warning("Unknown JSON-RPC method=%s", method)
        return {"jsonrpc": "2.0", "result": {}, "id": message_id}

    def build_server_info(self) -> dict[str, Any]:
        return {
            "klippy_connected": True,
            "klippy_state": "ready",
            "components": [],
            "failed_components": [],
            "registered_directories": [],
        }

    def build_printer_info(self) -> dict[str, Any]:
        return {
            "state": "ready",
            "state_message": "Panda Breath bridge for Prusa Core One",
            "hostname": "prusa-core-one-bridge",
            "software_version": "0.1",
            "cpu_info": "python",
        }

    def build_objects_list(self) -> dict[str, Any]:
        return {
            "objects": [
                "webhooks",
                "virtual_sdcard",
                "print_stats",
                "extruder",
                "heater_bed",
                "gcode_macro _KNOMI_STATUS",
            ]
        }

    def build_query_result(self, requested_objects: dict[str, Any] | None = None) -> dict[str, Any]:
        status = self._prusalink_client.get_status()
        requested_objects = requested_objects or {}
        payload = self._build_status_payload(status)

        if not requested_objects:
            requested_objects = {
                key: None for key in payload.keys()
            }

        filtered_status: dict[str, Any] = {}
        for object_name, requested_fields in requested_objects.items():
            if object_name not in payload:
                LOGGER.debug("Requested unknown object=%s", object_name)
                continue

            object_payload = payload[object_name]
            if requested_fields in (None, []):
                filtered_status[object_name] = object_payload
                continue

            filtered_status[object_name] = {
                field_name: object_payload[field_name]
                for field_name in requested_fields
                if field_name in object_payload
            }

        return {
            "status": filtered_status,
            "eventtime": time.time(),
        }

    def _build_status_payload(self, status: BridgeStatus) -> dict[str, Any]:
        knomi_status = "ok" if status.source_ok else "fallback"
        return {
            "webhooks": {"state": "ready"},
            "virtual_sdcard": {"progress": 0.0},
            "print_stats": {"state": "standby"},
            "extruder": {"temperature": 0.0, "target": 0.0},
            "heater_bed": {
                "temperature": status.bed_current,
                "target": status.bed_target,
            },
            "gcode_macro _KNOMI_STATUS": {
                "source_ok": status.source_ok,
                "status": knomi_status,
            },
        }


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "PandaPrusaBridge/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], fmt % args)

    @property
    def bridge_service(self) -> PandaBridgeService:
        return self.server.bridge_service  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path == "/websocket" and self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_websocket()
            return

        if self.path == "/healthz":
            self._send_json({"ok": True})
            return

        if self.path.startswith("/server/info"):
            self._send_json({"result": self.bridge_service.build_server_info()})
            return

        if self.path.startswith("/printer/info"):
            self._send_json({"result": self.bridge_service.build_printer_info()})
            return

        if self.path.startswith("/printer/objects/list"):
            self._send_json({"result": self.bridge_service.build_objects_list()})
            return

        if self.path.startswith("/printer/objects/query"):
            self._send_json({"result": self.bridge_service.build_query_result()})
            return

        LOGGER.warning("Unknown HTTP request path=%s", self.path)
        self._send_json({"result": {}}, status=404)

    def _handle_websocket(self) -> None:
        LOGGER.info("WebSocket upgrade from %s", self.client_address[0])
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(400, "Missing Sec-WebSocket-Key")
            return

        accept = base64.b64encode(
            hashlib.sha1(f"{key}{WS_GUID}".encode("utf-8")).digest()
        ).decode("ascii")

        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        while True:
            message = self._read_websocket_message()
            if message is None:
                return

            LOGGER.debug("WebSocket message: %s", message)
            try:
                decoded = json.loads(message)
            except json.JSONDecodeError:
                LOGGER.warning("Ignoring invalid JSON frame")
                continue

            response = self.bridge_service.handle_jsonrpc(decoded)
            if response is None:
                continue

            self.connection.sendall(build_websocket_frame(json.dumps(response)))

    def _read_websocket_message(self) -> str | None:
        first_bytes = self.rfile.read(2)
        if not first_bytes:
            return None

        first_byte, second_byte = first_bytes
        opcode = first_byte & 0x0F
        masked = (second_byte >> 7) & 1
        payload_length = second_byte & 0x7F

        if payload_length == 126:
            payload_length = int.from_bytes(self.rfile.read(2), "big")
        elif payload_length == 127:
            payload_length = int.from_bytes(self.rfile.read(8), "big")

        masking_key = self.rfile.read(4) if masked else b""
        payload = self.rfile.read(payload_length)

        if masked:
            payload = bytes(
                value ^ masking_key[index % 4]
                for index, value in enumerate(payload)
            )

        if opcode == 0x8:
            self.connection.sendall(build_websocket_frame(b"", opcode=0x8))
            return None

        if opcode == 0x9:
            self.connection.sendall(build_websocket_frame(payload, opcode=0xA))
            return ""

        if opcode != 0x1:
            LOGGER.info("Ignoring unsupported opcode=%s", opcode)
            return ""

        return payload.decode("utf-8", "replace")

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadingBridgeServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        bridge_service: PandaBridgeService,
    ):
        super().__init__(server_address, request_handler_class)
        self.bridge_service = bridge_service


def build_websocket_frame(payload: str | bytes, opcode: int = 0x1) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")

    payload_length = len(payload)
    frame = bytearray([0x80 | opcode])

    if payload_length < 126:
        frame.append(payload_length)
    elif payload_length < (1 << 16):
        frame.append(126)
        frame.extend(payload_length.to_bytes(2, "big"))
    else:
        frame.append(127)
        frame.extend(payload_length.to_bytes(8, "big"))

    frame.extend(payload)
    return bytes(frame)


def run_server(config: BridgeConfig) -> None:
    LOGGER.info(
        "Starting bridge listen=%s:%s prusa_host=%s status_path=%s",
        config.listen_host,
        config.listen_port,
        config.prusa_host,
        config.prusa_status_path,
    )
    service = PandaBridgeService(PrusaLinkClient(config))
    with ThreadingBridgeServer(
        (config.listen_host, config.listen_port),
        BridgeRequestHandler,
        service,
    ) as server:
        server.serve_forever()
