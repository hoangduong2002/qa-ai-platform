import base64
import json
import urllib.request
from pathlib import Path


BASE_URL = "http://172.76.10.44:11434"
MODEL = "llava:7b"
IMAGE_PATH = Path(r"F:\AI\qa-ai-platform\sample_requirement.png")


if not IMAGE_PATH.exists():
    raise FileNotFoundError(IMAGE_PATH)

image_bytes = IMAGE_PATH.read_bytes()
image_b64 = base64.b64encode(image_bytes).decode("utf-8")

print("Image:", IMAGE_PATH)
print("Image size:", len(image_bytes))
print("Base64 length:", len(image_b64))

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": "Describe this image. Extract all visible text.",
            "images": [image_b64],
        }
    ],
    "stream": False,
}

req = urllib.request.Request(
    f"{BASE_URL}/api/chat",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=180) as response:
    raw = response.read().decode("utf-8", errors="ignore")

print("Raw response:")
print(raw)

data = json.loads(raw)
print("\nExtracted:")
print(data.get("message", {}).get("content") or data.get("response"))