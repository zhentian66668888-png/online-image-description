# Online Image Description

A client-server application over IPv4 TCP. Each client keeps one persistent connection to the server. Clients can upload JPEG or PNG images, list stored images, request an English caption, download the original bytes, or remove an image. The server listens on TCP port `18333` by default and can caption images with a local vision-language model, or return a fixed mock caption while you test the protocol.

The client uses only the Python standard library. The server implements the socket layer, shared in-memory image store, and optional on-device CPU inference.

## Features

- Persistent IPv4 TCP connections and clean close on `QUIT`
- Length-prefixed framing so messages stay aligned on a byte stream
- Six client commands: `UPLOAD`, `LIST`, `DESCRIBE`, `DOWNLOAD`, `REMOVE`, `QUIT`
- Upload JPEG/PNG images up to 5 MiB and 20 million pixels
- Server store limited to 20 images and 50 MiB; IDs start at `0000` and are not reused
- Captions are generated on the first `DESCRIBE` and reused afterwards
- `DOWNLOAD` writes the original bytes and will not overwrite an existing file
- Recoverable errors stay on the same connection

## Protocol

Every message is a 10-byte ASCII decimal length header, zero-padded, followed by 1 to 5,242,880 payload bytes. The length counts payload bytes only. Text is UTF-8; images are sent as the original file bytes.

Example: the five-byte payload `HELLO` is sent as `0000000005HELLO`.

| Command | Client sends | Server replies |
| --- | --- | --- |
| `UPLOAD` | Text `UPLOAD <filename>`, then a second message with the image bytes | `OK <image_id>` or `ERROR - <reason>` |
| `LIST` | `LIST` | `OK` followed by the image list, or `No images` |
| `DESCRIBE` | `DESCRIBE <image_id>` | `OK` followed by the caption, or an error |
| `DOWNLOAD` | `DOWNLOAD <image_id>` | `OK <filename>` plus an image message, or an error and no image |
| `REMOVE` | `REMOVE <image_id>` | `OK` or an error |
| `QUIT` | `QUIT` | `OK`, then the client closes the socket |

Commands and their arguments are typed on separate lines in the client. The client adds the `client:` and `server:` prefixes when printing to the terminal.

## Requirements

- Python 3.11 or later
- Client: standard library only
- Server, mock mode: [Pillow](https://pypi.org/project/Pillow/) is used when a description is requested
- Server, real model: PyTorch, Transformers, `huggingface_hub`, and Pillow, plus the local [SmolVLM-256M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct) files

Model weights are not included in this repository.

## Run the server

From this directory:

```bash
# Protocol testing without the model
python ImageDescriptionServer.py --backend mock

# Download the pinned SmolVLM-256M files into models/smolvlm-256m
python ImageDescriptionServer.py --download-model

# Run with the local model (CPU)
python ImageDescriptionServer.py --model-dir ./models/smolvlm-256m
```

The server is ready when it prints `READY host=0.0.0.0 port=18333`. Use `--host 127.0.0.1` to listen only on loopback.

## Run the client

In a second terminal:

```bash
python ImageDescriptionClient.py 127.0.0.1 18333
```

Then enter commands and their values on separate lines, for example:

```text
UPLOAD
./cat.jpg
LIST
DESCRIBE
0000
DOWNLOAD
0000
cat_copy.jpg
REMOVE
0000
QUIT
```

## Project layout

- `ImageDescriptionServer.py` — listening socket, framed send/receive, command handling, and local captioning
- `ImageDescriptionClient.py` — standard-library client for the six commands
