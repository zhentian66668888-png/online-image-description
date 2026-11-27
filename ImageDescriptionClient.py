"""Standard-library IPv4 TCP client for the Online Image Description System."""

import argparse
import math
import socket
from pathlib import Path

HEADER_SIZE = 10
MAX_MESSAGE_BYTES = 5 * 1024 * 1024
MAX_COMMAND_BYTES = 1024


def recv_exact(conn, count):
    """Read a byte count; distinguish clean EOF from a truncated message."""
    data = bytearray()
    while len(data) < count:
        chunk = conn.recv(count - len(data))
        if not chunk:
            if not data:
                return None
            raise ConnectionError("Connection closed during a message")
        data.extend(chunk)
    return bytes(data)


def receive_message(conn):
    """Receive one bounded length-prefixed payload, without over-reading."""
    header = recv_exact(conn, HEADER_SIZE)
    if header is None:
        raise ConnectionError("Server closed the connection")
    if not header.isdigit():
        raise ValueError("Invalid length header from server")
    length = int(header)
    if not 1 <= length <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid message length from server")
    payload = recv_exact(conn, length)
    if payload is None:
        raise ConnectionError("Server closed before message data")
    return payload


def send_message(conn, payload):
    """Send a complete frame, counting encoded bytes instead of characters."""
    if not isinstance(payload, bytes):
        raise TypeError("Payload must be bytes")
    if not 1 <= len(payload) <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid message length")
    conn.sendall(f"{len(payload):010d}".encode("ascii") + payload)


def local_error(reason):
    print("client: ERROR - " + reason, flush=True)


def read_value():
    """All commands and subsequent values use separate input lines."""
    return input("client: ").strip()


def local_path(value):
    """Accept ordinary paths and optionally quoted paths containing spaces."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not value or "\x00" in value:
        raise ValueError("Invalid local path")
    return Path(value)


def send_command(conn, text):
    payload = text.encode("utf-8")
    if not 1 <= len(payload) <= MAX_COMMAND_BYTES:
        local_error("Command must contain 1 to 1024 UTF-8 bytes")
        return False
    send_message(conn, payload)
    return True


def print_reply(conn):
    reply = receive_message(conn).decode("utf-8")
    for line in reply.split("\n"):
        print("server: " + line, flush=True)
    return reply


def upload(conn, value):
    """Validate local input before sending either UPLOAD message."""
    try:
        path = local_path(value)
        filename = path.name
        if (not filename or len(filename) > 255 or filename in {".", ".."}
                or any(char in filename for char in "/\\\r\n\x00")
                or filename != filename.strip()):
            raise ValueError("Invalid filename")
        with path.open("rb") as stream:
            if path.stat().st_size > MAX_MESSAGE_BYTES:
                raise ValueError("File exceeds 5 MiB")
            # Bound the read even if the file grows after stat().
            data = stream.read(MAX_MESSAGE_BYTES + 1)
        if not data:
            raise ValueError("File is empty")
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError("File exceeds 5 MiB")
    except FileNotFoundError:
        local_error("File not found")
        return
    except OSError:
        local_error("Cannot read file")
        return
    except ValueError as error:
        local_error(str(error))
        return
    if send_command(conn, "UPLOAD " + filename):
        send_message(conn, data)
        print_reply(conn)


def download(conn, image_id, output):
    """Drain the whole download before reporting local file errors."""
    if not send_command(conn, "DOWNLOAD " + image_id):
        return
    reply = print_reply(conn)
    if not reply.startswith("OK "):
        return
    data = receive_message(conn)
    path = None
    created = False
    try:
        path = local_path(output)
        # Exclusive creation also prevents overwriting in a race with another process.
        with path.open("xb") as stream:
            created = True
            stream.write(data)
    except FileExistsError:
        local_error("Output file already exists")
    except (OSError, ValueError) as error:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        reason = str(error) if isinstance(error, ValueError) else "Cannot save file"
        local_error(reason)
    else:
        print("client: Saved to " + output, flush=True)


def interact(conn):
    """Execute commands in order over one persistent connection."""
    while True:
        text = read_value()
        if not text:
            continue
        command = text.upper()
        command_parts = command.split(maxsplit=1)
        if (len(command_parts) > 1
                and command_parts[0] in {"UPLOAD", "LIST", "DESCRIBE",
                                         "DOWNLOAD", "REMOVE", "QUIT"}):
            # Do not dispatch malformed terminal input as a raw wire command.
            # In particular, DOWNLOAD returns two frames, not just a text reply.
            local_error("Enter the command and its arguments on separate lines")
            continue
        if command == "UPLOAD":
            upload(conn, read_value())
        elif command == "DOWNLOAD":
            image_id = read_value()
            output = read_value()
            download(conn, image_id, output)
        elif command in {"DESCRIBE", "REMOVE"}:
            image_id = read_value()
            if send_command(conn, command + " " + image_id):
                print_reply(conn)
        else:
            # Forward unknown commands so the displayed error is the actual reply.
            if send_command(conn, command):
                reply = print_reply(conn)
                if command == "QUIT" and reply == "OK":
                    return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Server IPv4 address or hostname")
    parser.add_argument("port", nargs="?", type=int, default=18333)
    parser.add_argument("--timeout", type=float, default=300,
                        help="Socket timeout in seconds (default: 300)")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be 1..65535")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Timeout must be a finite positive number")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conn:
            try:
                conn.settimeout(args.timeout)
            except (OverflowError, ValueError):
                parser.error("Timeout is outside the range supported by this platform")
            conn.connect((args.host, args.port))
            interact(conn)
    except EOFError:
        print("\nclient: Input ended; connection closed", flush=True)
    except KeyboardInterrupt:
        print("\nclient: Interrupted; connection closed", flush=True)
    except socket.timeout:
        local_error("Network operation timed out")
        return 1
    except socket.gaierror:
        local_error("Cannot resolve server IPv4 address")
        return 1
    except ConnectionError:
        local_error("Connection lost or message incomplete")
        return 1
    except OSError as error:
        local_error("Network I/O failed (error " + str(error.errno) + ")")
        return 1
    except ValueError as error:
        local_error(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
