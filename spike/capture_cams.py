"""Capture named gz camera topics, save frames/<name>.npy, exit when all arrive."""
import sys, time
import numpy as np
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image

cams = sys.argv[1].split(",") if len(sys.argv) > 1 else ["cam_oblique", "cam_top"]
got = {}
node = Node()

def mk(name):
    def cb(m):
        if name in got:
            return
        raw = np.frombuffer(m.data, dtype=np.uint8)
        got[name] = raw[: m.height * m.width * 3].reshape(m.height, m.width, 3)
        np.save(f"/workspace/frames/{name}.npy", got[name])
    return cb

for c in cams:
    node.subscribe(Image, c, mk(c))

t0 = time.time()
while time.time() - t0 < 100 and not all(c in got for c in cams):
    time.sleep(0.3)

for c in cams:
    if c in got:
        a = got[c]
        g = ((a[:, :, 1] > a[:, :, 0] + 12) & (a[:, :, 1] > a[:, :, 2] + 12)).mean() * 100
        print(f"{c:12s}: {a.shape} std={a.std():.1f} green%={g:.1f} -> {'NON-BLANK' if a.std()>5 else 'BLANK'}", flush=True)
    else:
        print(f"{c:12s}: NO MSG", flush=True)
