import math, numpy as np, sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from eva_tentacle import geometry as G

def curled(n=12, length=1300.0, curl=300.0, power=2.0, twist=40.0):
    seg = length / n
    w = np.array([((i + 1) / n) ** power for i in range(n)]); w *= math.radians(curl) / w.sum()
    tw = math.radians(twist) / n
    R = np.eye(3); p = np.zeros(3); joints = [p.copy()]; ups = []
    def rx(a): c, s = math.cos(a), math.sin(a); return np.array([[1,0,0],[0,c,-s],[0,s,c]])
    def ry(a): c, s = math.cos(a), math.sin(a); return np.array([[c,0,s],[0,1,0],[-s,0,c]])
    for i in range(n):
        R = R @ rx(-w[i]) @ ry(tw)
        ups.append(R[:, 2]); p = p + R[:, 1] * seg; joints.append(p.copy())
    return np.array(joints), np.array(ups)
