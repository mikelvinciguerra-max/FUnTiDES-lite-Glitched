import numpy as np
import json
import math

def speed(sismo_file):
    data = np.fromfile(sismo_file, dtype=np.float32).reshape(3, 1499)[0:2,]

    meta = json.load(open("../sismos/sismos_meta.json", "r"))
    coords = meta["receivers"]
    dt = meta["dt"]

    source = [1000, 1000, 1000]

    d = np.abs(math.dist(source, coords[0]) - math.dist(source, coords[1]))

    i1, i2 = False, False
    eps = 0.001

    for i in range(len(data[0])):
        if (data[0][i] > eps and i1 == False):
            i1 = i
        if (data[1][i] > eps and i2 == False):
            i2 = i 
        if (i1 and i2):
            break 

    delta_t = np.abs(i1-i2)*dt

    v = d/delta_t

    print(v, "m/s")
        



if __name__  == "__main__":
    file = "../sismos/sismos.bin"

    speed(file)
