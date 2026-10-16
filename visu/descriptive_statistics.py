import matplotlib.pyplot as plt
import numpy as np


def statistics_pressure(snapshot_file):
    num_nodes = 2050401
    nodes_file = "../snapshots/nodes.bin"

    nodes = np.fromfile(nodes_file, dtype=np.float32).reshape((num_nodes, 3))
    P = np.fromfile(snapshot_file, dtype=np.float32)
    Z = nodes[:, 2]

    Z_mean = []
    tab_mean = []
    min_tab = []
    max_tab = []
    median_tab = []

    for i in range(0, 2001, 100):
        tmp = P[Z==i]
        Z_mean.append(i)
        tab_mean.append(tmp.mean())
        min_tab.append(min(tmp))
        max_tab.append(max(tmp))
        median_tab.append(np.median(tmp))


    plt.figure()
    plt.plot(Z_mean, tab_mean, color="blue", label="Average Pressure")
    plt.plot(Z_mean, min_tab, color="green", label="Min pressure values")
    plt.plot(Z_mean, max_tab, color="red", label="Max pressure values")
    plt.plot(Z_mean, median_tab, color="orange", label="Median pressure")
    plt.legend()
    plt.xlabel("Height (Z)")
    plt.ylabel("Pressure (Pa)")
    plt.title("Some stats about pressure")
    plt.show()



if __name__ == "__main__":
    file = "../snapshots/snapshot_01450.bin"

    statistics_pressure(file)
