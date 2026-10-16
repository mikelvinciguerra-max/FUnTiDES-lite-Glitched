import os
import numpy as np
import json
import matplotlib.pyplot as plt
import seaborn as sns
import sys
import pyvista as pv

def visualize2D_snapshots(snapshot_file):
    num_nodes = 2050401
    nodes_file = "snapshots/nodes.bin"

    nodes = np.fromfile(nodes_file, dtype=np.float32).reshape((num_nodes, 3))
    
    pressure_1d = np.fromfile(snapshot_file, dtype=np.float32)

    z_coords = nodes[:, 2]
    mid_z = 1000
    
    slice_mask = np.abs(z_coords - mid_z) < 1e-5

    X = nodes[slice_mask, 0]
    Y = nodes[slice_mask, 1]
    P = pressure_1d[slice_mask]

    fig, ax = plt.subplots(figsize=(8, 6))

    pressure_map = ax.tricontourf(X, Y, P, levels=30, cmap="viridis")

    fig.colorbar(pressure_map, ax=ax, label="Pressure (Pa)")

    ax.set_title(f"2D Pressure Field Map (XY Plane at Z ≈ {mid_z:.2f})")
    ax.set_xlabel("X Coordinate")
    ax.set_ylabel("Y Coordinate")

    plt.show()

def visualize3D_snapshots(snapshot_file):
    num_nodes = 2050401
    nodes_file = "snapshots/nodes.bin"

    nodes = np.fromfile(nodes_file, dtype=np.float32).reshape((num_nodes, 3))

    # X = nodes[:, 0]
    # Y = nodes[:, 1]
    # Z = nodes[:, 2]
    # P = np.fromfile(snapshot_file, dtype=np.float32)

    # fig = plt.figure()
    # ax = fig.add_subplot(111, projection="3d")
    # scatter_plot = ax.scatter(X, Y, Z, c=P, cmap="viridis", s=2, alpha=0.5)

    # fig.colorbar(scatter_plot, ax=ax, label="Pressure (Pa)")
    # ax.set_title("3D Pressure Field Map")
    # ax.set_xlabel("X Coordinate")
    # ax.set_ylabel("Y Coordinate")
    # ax.set_zlabel("Z Coordinate")
    # plt.show()

    P = np.fromfile(snapshot_file, dtype=np.float32)
    point_cloud = pv.PolyData(nodes)
    plotter = pv.Plotter()
    plotter.add_mesh(point_cloud, scalars=P, cmap="viridis", point_size=4)
    # plotter.add_scalar_bar(title="Pressure (Pa)")
    plotter.show(title="3D Pressure Field Map")


def visualize_sismo(sismo_file):
    data = np.fromfile(sismo_file, dtype=np.float32).reshape(3, 1499)

    X = np.arange(data.shape[1])

    plt.figure()
    plt.plot(X, data[0], color="blue", label="1st receiver")
    plt.plot(X, data[1], color="orange", label="2nd receiver")
    plt.plot(X, data[2], color="green", label="3rd receiver")
    plt.xlabel("Time")
    plt.ylabel("Amplitude")
    plt.title("Sismic Signals")
    plt.legend()
    plt.show() 


    
if __name__ == "__main__":
    if (len(sys.argv) != 2 and len(sys.argv) != 3):
        print("Missing argument(s) !")
        sys.exit(1)
    elif (not sys.argv[1].endswith(".bin")):
        print("The argument must be a .bin file !")
        sys.exit(1)
    elif (sys.argv[1].startswith("../snapshot")):
        if (sys.argv[2] == "2d" or sys.argv[2] == "2D"):
            visualize2D_snapshots(sys.argv[1])
        elif (sys.argv[2] == "3d" or sys.argv[2] == "3D"):
            visualize3D_snapshots(sys.argv[1]) 
        else:
            print("The second argument must be either '2d' or '3d' !")
            sys.exit(1)
    elif (sys.argv[1].startswith("../sismos")):
        visualize_sismo(sys.argv[1])
    else:
        print("The argument must be either a snapshot or a sismo file !")
        sys.exit(1)
