"""Modbus TCP protocol handling for the fake Solis probe."""

from __future__ import annotations

import socketserver
import struct

from . import config, event_log, registers


def exception_pdu(fc: int, code: int) -> bytes:
    """Build a Modbus exception PDU."""
    return bytes([fc | 0x80, code])


def device_id_objects() -> list[tuple[int, bytes]]:
    """Return the configured Modbus device-identification objects."""
    vendor = str(config.OPTIONS.get("fake_vendor", "Ginlong"))
    model = str(config.OPTIONS.get("fake_inverter_model", "Solis S6-EH1P"))
    serial = str(config.OPTIONS.get("fake_serial", "S2WLSTFAKE001"))
    logger_model = str(config.OPTIONS.get("fake_logger_model", "S2-WL-ST"))
    return [
        (0x00, vendor.encode("ascii", "ignore")),
        (0x01, model.encode("ascii", "ignore")),
        (0x02, b"1.00"),
        (0x03, serial.encode("ascii", "ignore")),
        (0x04, logger_model.encode("ascii", "ignore")),
    ]


class ModbusHandler(socketserver.BaseRequestHandler):
    """Serve the fake inverter's Modbus TCP request surface."""

    def handle(self) -> None:
        peer_ip, peer_port = self.client_address[:2]
        event_log.log_event(
            "modbus_connection_open", peer_ip=peer_ip, peer_port=peer_port
        )
        try:
            while True:
                header = self._recv_exact(7)
                if header is None:
                    return
                tid, proto, length, uid = struct.unpack(">HHHB", header)
                if length < 1 or length > 260:
                    event_log.log_event(
                        "modbus_bad_mbap_length",
                        peer_ip=peer_ip,
                        transaction_id=tid,
                        length=length,
                    )
                    return
                pdu = self._recv_exact(length - 1)
                if pdu is None:
                    return
                if not pdu:
                    continue
                fc = pdu[0]
                if config.OPTIONS.get("log_raw_hex", False):
                    event_log.log_event(
                        "modbus_request_raw",
                        peer_ip=peer_ip,
                        transaction_id=tid,
                        protocol_id=proto,
                        unit_id=uid,
                        length=length,
                        pdu_hex=event_log.hex_bytes(pdu),
                    )
                try:
                    resp_pdu = self.process_pdu(peer_ip, uid, fc, pdu)
                except Exception as exc:
                    event_log.log_event(
                        "modbus_process_error",
                        peer_ip=peer_ip,
                        unit_id=uid,
                        fc=fc,
                        error=str(exc),
                    )
                    resp_pdu = exception_pdu(fc, 4)
                resp_hdr = struct.pack(">HHHB", tid, 0, len(resp_pdu) + 1, uid)
                self.request.sendall(resp_hdr + resp_pdu)
                if config.OPTIONS.get("log_raw_hex", False):
                    event_log.log_event(
                        "modbus_response_raw",
                        peer_ip=peer_ip,
                        transaction_id=tid,
                        unit_id=uid,
                        pdu_hex=event_log.hex_bytes(resp_pdu),
                    )
        except ConnectionResetError:
            event_log.log_event(
                "modbus_connection_reset", peer_ip=peer_ip, peer_port=peer_port
            )
        except Exception as exc:
            event_log.log_event(
                "modbus_connection_error",
                peer_ip=peer_ip,
                peer_port=peer_port,
                error=str(exc),
            )
        finally:
            event_log.log_event(
                "modbus_connection_close", peer_ip=peer_ip, peer_port=peer_port
            )

    def _recv_exact(self, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def process_pdu(self, peer_ip: str, uid: int, fc: int, pdu: bytes) -> bytes:
        """Process one Modbus PDU and return its response PDU."""
        if fc in (1, 2):
            return self._read_bits(peer_ip, uid, fc, pdu)
        if fc in (3, 4):
            return self._read_registers(peer_ip, uid, fc, pdu)
        if fc == 5:
            return self._write_single_coil(peer_ip, uid, pdu)
        if fc == 6:
            return self._write_single_register(peer_ip, uid, pdu)
        if fc == 8:
            return pdu  # diagnostics echo
        if fc == 15:
            return self._write_multiple_coils(peer_ip, uid, pdu)
        if fc == 16:
            return self._write_multiple_registers(peer_ip, uid, pdu)
        if fc == 17:
            return self._report_server_id(peer_ip, uid)
        if fc == 43:
            return self._read_device_id(peer_ip, uid, pdu)
        event_log.log_event("modbus_unsupported_function", peer_ip=peer_ip, fc=fc)
        return exception_pdu(fc, 1)

    def _read_bits(self, peer_ip: str, uid: int, fc: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(fc, 3)
        start, qty = struct.unpack(">HH", pdu[1:5])
        event_log.log_event(
            "modbus_read_bits",
            peer_ip=peer_ip,
            fc=fc,
            unit_id=uid,
            start=start,
            qty=qty,
        )
        if qty < 1 or qty > 2000:
            return exception_pdu(fc, 3)
        byte_count = (qty + 7) // 8
        return bytes([fc, byte_count]) + bytes(byte_count)

    def _read_registers(self, peer_ip: str, uid: int, fc: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(fc, 3)
        start, qty = struct.unpack(">HH", pdu[1:5])
        event_log.log_event(
            "modbus_read_registers",
            peer_ip=peer_ip,
            fc=fc,
            unit_id=uid,
            start=start,
            qty=qty,
            end=start + qty - 1,
        )
        if qty < 1 or qty > 125:
            return exception_pdu(fc, 3)
        data = b"".join(
            struct.pack(">H", registers.get_register(start + index))
            for index in range(qty)
        )
        return bytes([fc, len(data)]) + data

    def _write_single_coil(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(5, 3)
        addr, value = struct.unpack(">HH", pdu[1:5])
        event_log.log_event(
            "modbus_write_single_coil", peer_ip=peer_ip, addr=addr, value=value
        )
        return pdu[:5]

    def _write_single_register(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(6, 3)
        addr, value = struct.unpack(">HH", pdu[1:5])
        mirrored = bool(config.OPTIONS.get("mirror_writes", False))
        event_log.log_event(
            "modbus_write_single_register",
            peer_ip=peer_ip,
            addr=addr,
            value=value,
            mirrored=mirrored,
        )
        if mirrored:
            registers.set_register(addr, value)
        return pdu[:5]

    def _write_multiple_coils(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 6:
            return exception_pdu(15, 3)
        addr, qty, byte_count = struct.unpack(">HHB", pdu[1:6])
        event_log.log_event(
            "modbus_write_multiple_coils",
            peer_ip=peer_ip,
            addr=addr,
            qty=qty,
        )
        return bytes([15]) + struct.pack(">HH", addr, qty)

    def _write_multiple_registers(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 6:
            return exception_pdu(16, 3)
        addr, qty, byte_count = struct.unpack(">HHB", pdu[1:6])
        raw = pdu[6 : 6 + byte_count]
        values = []
        for index in range(0, len(raw), 2):
            if index + 1 < len(raw):
                values.append(struct.unpack(">H", raw[index : index + 2])[0])
        mirrored = bool(config.OPTIONS.get("mirror_writes", False))
        event_log.log_event(
            "modbus_write_multiple_registers",
            peer_ip=peer_ip,
            addr=addr,
            qty=qty,
            values=values,
            mirrored=mirrored,
        )
        if mirrored:
            for offset, value in enumerate(values[:qty]):
                registers.set_register(addr + offset, value)
        return bytes([16]) + struct.pack(">HH", addr, qty)

    def _report_server_id(self, peer_ip: str, uid: int) -> bytes:
        vendor = str(config.OPTIONS.get("fake_vendor", "Ginlong"))
        model = str(config.OPTIONS.get("fake_inverter_model", "Solis S6-EH1P"))
        text = f"{vendor} Solis {model}".encode("ascii", "ignore")[:240]
        payload = b"\x01\xff" + text
        event_log.log_event("modbus_report_server_id", peer_ip=peer_ip)
        return bytes([17, len(payload)]) + payload

    def _read_device_id(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 4 or pdu[1] != 0x0E:
            return exception_pdu(43, 1)
        code = pdu[2]
        obj_id = pdu[3]
        objects = device_id_objects()
        if code == 4:
            selected = [
                (object_id, value)
                for object_id, value in objects
                if object_id == obj_id
            ]
        else:
            selected = [
                (object_id, value)
                for object_id, value in objects
                if object_id >= obj_id
            ]
        selected = selected[:5]
        body = bytearray([0x2B, 0x0E, code, 0x03, 0x00, 0x00, len(selected)])
        for object_id, value in selected:
            value = value[:240]
            body.extend([object_id, len(value)])
            body.extend(value)
        event_log.log_event(
            "modbus_read_device_id",
            peer_ip=peer_ip,
            objects=[object_id for object_id, _ in selected],
        )
        return bytes(body)
